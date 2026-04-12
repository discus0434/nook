from __future__ import annotations

import datetime
import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Callable, Protocol

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from nook.services.llm_client import create_client
from nook.services.runtime import JobInvoker, RuntimeSettings, build_job_invoker
from nook.services.storage import StorageBackend, build_storage_backend
from nook.services.viewer.chat import build_chat_prompt, collect_additional_context
from nook.services.viewer.content import (
    build_initial_render,
    load_viewer_page,
    read_article_or_404,
    read_markdown_or_404,
    trigger_retry,
)
from nook.services.viewer.fetch import fetch_url_content
from nook.services.viewer.weather import get_weather_data

STATIC_DIR = Path(__file__).resolve().parent / "static"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


class SearchChatClient(Protocol):
    def chat_with_search(self, prompt: str) -> str: ...


WeatherProvider = Callable[[], dict[str, str]]
ContentFetcher = Callable[[str], str | None]
ChatClientFactory = Callable[[], SearchChatClient]


def create_app(
    storage_backend: StorageBackend,
    job_invoker: JobInvoker,
    weather_provider: WeatherProvider = get_weather_data,
    content_fetcher: ContentFetcher = fetch_url_content,
    chat_client_factory: ChatClientFactory | None = None,
) -> FastAPI:
    app = FastAPI()
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    client_factory = chat_client_factory or _default_chat_client_factory
    asset_version = _static_asset_version()

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request, date: str | None = None):
        target_day = _resolve_day(date)
        page = load_viewer_page(
            storage_backend=storage_backend,
            target_day=target_day,
            weather_data=weather_provider(),
        )
        initial_render = build_initial_render(page)
        response = templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "request": request,
                "asset_version": asset_version,
                "page": page,
                "initial_render": initial_render,
                "page_state_json": json.dumps(page.to_state(), ensure_ascii=False),
            },
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/weather", response_class=JSONResponse)
    async def weather() -> dict[str, str]:
        return weather_provider()

    @app.post("/chat/{topic_id}")
    async def chat(topic_id: str, request: Request) -> dict[str, str]:
        data = await request.json()
        message = data.get("message", "")
        chat_history = data.get("chat_history", "なし")
        target_day = _resolve_day(data.get("date"))
        article = read_article_or_404(
            storage_backend=storage_backend,
            app_name=topic_id,
            target_day=target_day,
            article_id=data.get("article_id", ""),
        )
        additional_context = collect_additional_context(
            markdown=article.markdown,
            message=message,
            content_fetcher=content_fetcher,
        )
        response_text = client_factory().chat_with_search(
            build_chat_prompt(
                markdown=article.markdown,
                additional_context=additional_context,
                chat_history=chat_history,
                message=message,
            )
        )
        return {"response": response_text}

    @app.get("/api/markdown/{app_name}")
    async def get_markdown_content(
        app_name: str,
        date: str | None = None,
        previous_updated_at: str | None = None,
    ) -> dict[str, object]:
        return read_markdown_or_404(
            storage_backend=storage_backend,
            app_name=app_name,
            target_day=_resolve_day(date),
            previous_updated_at=_resolve_datetime(previous_updated_at),
        )

    @app.post("/retry/{app_name}")
    async def retry_job(app_name: str) -> JSONResponse:
        return JSONResponse(
            status_code=202,
            content=trigger_retry(job_invoker=job_invoker, app_name=app_name),
        )

    return app


def build_app_from_env() -> FastAPI:
    storage_backend = build_storage_backend(os.environ)
    job_invoker = build_job_invoker(os.environ)
    return create_app(storage_backend=storage_backend, job_invoker=job_invoker)


def _default_chat_client_factory() -> SearchChatClient:
    return create_client(use_search=True)


@lru_cache(maxsize=1)
def _static_asset_version() -> str:
    digest = hashlib.sha256()
    for path in sorted(STATIC_DIR.iterdir(), key=lambda item: item.name):
        if not path.is_file():
            continue
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def _resolve_day(day_text: str | None) -> datetime.date:
    if day_text is None:
        return datetime.date.today()
    return datetime.date.fromisoformat(day_text)


def _resolve_datetime(value: str | None) -> datetime.datetime | None:
    if value is None:
        return None
    return datetime.datetime.fromisoformat(value)


if __name__ == "__main__":
    import uvicorn

    settings = RuntimeSettings.from_env(os.environ)
    uvicorn.run(
        build_app_from_env(),
        host=settings.local_host,
        port=settings.local_port,
    )
