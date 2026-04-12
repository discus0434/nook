from __future__ import annotations

import hashlib
import json
import re
import traceback
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from html import escape

import markdown
from bs4 import BeautifulSoup
from fastapi import HTTPException

from nook.services.runtime import JobInvoker, get_viewer_services
from nook.services.storage import StorageBackend
from nook.services.viewer.models import (
    ViewerArticleState,
    ViewerHeading,
    ViewerInitialRender,
    ViewerPage,
    ViewerRenderedArticle,
    ViewerTab,
)

TAB_LABELS = {
    "tech_news": "News",
    "tech_feed": "Feeds",
    "product_hunt": "ProductHunt",
    "hacker_news": "HN",
    "github_trending": "GitHub",
    "reddit_explorer": "Reddit",
    "paper_summarizer": "Papers",
    "google_alerts": "Alerts",
}
VIEWER_TAB_PRIORITY = (
    "tech_news",
    "tech_feed",
    "hacker_news",
    "product_hunt",
    "github_trending",
    "paper_summarizer",
    "google_alerts",
)

ARTICLE_IDENTITY_STATE_VERSION = 1


def viewer_service_names() -> list[str]:
    service_names = [definition.name for definition in get_viewer_services()]
    priority_by_name = {
        service_name: index for index, service_name in enumerate(VIEWER_TAB_PRIORITY)
    }
    indexed_names = list(enumerate(service_names))
    ordered_names = sorted(
        indexed_names,
        key=lambda item: (
            priority_by_name.get(item[1], len(priority_by_name)),
            item[0],
        ),
    )
    return [service_name for _, service_name in ordered_names]


def load_viewer_page(
    storage_backend: StorageBackend,
    target_day: date,
    weather_data: dict[str, str],
) -> ViewerPage:
    contents: dict[str, str] = {}
    articles: dict[str, list[ViewerRenderedArticle]] = {}
    markdown_exists: dict[str, bool] = {}
    markdown_updated_at: dict[str, str | None] = {}
    service_names = viewer_service_names()

    for service_name in service_names:
        record = storage_backend.read_markdown_record(service_name, target_day)
        content = record.content if record is not None else ""
        contents[service_name] = content
        article_states = (
            _resolve_article_states(
                storage_backend=storage_backend,
                app_name=service_name,
                target_day=target_day,
                markdown_text=content,
            )
            if record is not None
            else []
        )
        articles[service_name] = _render_articles(article_states)
        markdown_exists[service_name] = record is not None
        markdown_updated_at[service_name] = _serialize_timestamp(
            record.updated_at if record is not None else None
        )

    return ViewerPage(
        date=target_day.isoformat(),
        app_names=service_names,
        contents=contents,
        articles=articles,
        markdown_exists=markdown_exists,
        markdown_updated_at=markdown_updated_at,
        weather_data=weather_data,
    )


def build_initial_render(page: ViewerPage) -> ViewerInitialRender:
    current_app = _initial_app_name(page)
    tabs = [
        ViewerTab(
            app_name=app_name,
            label=display_label(app_name),
            is_active=app_name == current_app,
            has_markdown=page.markdown_exists.get(app_name, False),
        )
        for app_name in page.app_names
    ]
    if current_app is None:
        return ViewerInitialRender(
            current_app=None,
            tabs=tabs,
            article_title="",
            article_meta=page.date,
            articles=[],
            missing_message=None,
            headings=[],
            has_markdown=False,
        )

    current_articles = page.articles.get(current_app, [])
    has_markdown = page.markdown_exists.get(current_app, False) and bool(
        current_articles
    )
    updated_at = page.markdown_updated_at.get(current_app)
    article_meta = (
        f"{page.date} · Updated {updated_at}"
        if page.markdown_exists.get(current_app, False) and updated_at
        else page.date
    )
    if not has_markdown:
        return ViewerInitialRender(
            current_app=current_app,
            tabs=tabs,
            article_title=display_label(current_app),
            article_meta=article_meta,
            articles=[],
            missing_message=f"Content for {page.date} not found.",
            headings=[],
            has_markdown=False,
        )

    headings = [heading for article in current_articles for heading in article.headings]
    return ViewerInitialRender(
        current_app=current_app,
        tabs=tabs,
        article_title=display_label(current_app),
        article_meta=article_meta,
        articles=current_articles,
        missing_message=None,
        headings=headings,
        has_markdown=True,
    )


def split_markdown_into_articles(
    app_name: str,
    markdown_text: str,
) -> list[ViewerArticleState]:
    return _assign_article_ids(
        app_name=app_name,
        sections=_split_markdown_sections(markdown_text),
        previous_entries=[],
    )


def _resolve_article_states(
    storage_backend: StorageBackend,
    app_name: str,
    target_day: date,
    markdown_text: str,
) -> list[ViewerArticleState]:
    sections = _split_markdown_sections(markdown_text)
    state_key = _article_identity_state_key(target_day)
    previous_state_text = storage_backend.read_state(app_name, state_key)
    previous_entries = _load_article_identity_state(previous_state_text)
    if not sections:
        serialized_state = _serialize_article_identity_state([])
        if previous_state_text != serialized_state:
            storage_backend.write_state(app_name, state_key, serialized_state)
        return []

    article_states = _assign_article_ids(
        app_name=app_name,
        sections=sections,
        previous_entries=previous_entries,
    )
    serialized_state = _serialize_article_identity_state(article_states)
    if previous_state_text != serialized_state:
        storage_backend.write_state(app_name, state_key, serialized_state)
    return article_states


def _split_markdown_sections(markdown_text: str) -> list[str]:
    if not markdown_text.strip():
        return []

    sections: list[str] = []
    current_lines: list[str] = []
    for line in markdown_text.splitlines():
        if line.strip() == "---":
            section = "\n".join(current_lines).strip()
            if section:
                sections.append(section)
            current_lines = []
            continue
        current_lines.append(line)

    final_section = "\n".join(current_lines).strip()
    if final_section:
        sections.append(final_section)
    return sections


def _assign_article_ids(
    app_name: str,
    sections: list[str],
    previous_entries: list[dict[str, str]],
) -> list[ViewerArticleState]:
    current_canonicals = [
        _canonicalize_article_markdown(section) for section in sections
    ]
    current_ids: list[str | None] = [None] * len(sections)
    previous_canonicals = [entry["canonical_markdown"] for entry in previous_entries]

    if previous_entries:
        matcher = SequenceMatcher(
            a=previous_canonicals,
            b=current_canonicals,
            autojunk=False,
        )
        for block in matcher.get_matching_blocks():
            for offset in range(block.size):
                previous_index = block.a + offset
                current_index = block.b + offset
                current_ids[current_index] = previous_entries[previous_index][
                    "article_id"
                ]

    used_ids = {entry["article_id"] for entry in previous_entries}
    article_states: list[ViewerArticleState] = []
    for index, section in enumerate(sections):
        article_id = current_ids[index]
        if article_id is None:
            article_id = _allocate_article_id(
                app_name=app_name,
                canonical_markdown=current_canonicals[index],
                used_ids=used_ids,
            )
        used_ids.add(article_id)
        article_states.append(
            ViewerArticleState(
                article_id=article_id,
                title=_extract_article_title(section, index),
                markdown=section,
            )
        )
    return article_states


def read_markdown_or_404(
    storage_backend: StorageBackend,
    app_name: str,
    target_day: date,
    previous_updated_at: datetime | None = None,
) -> dict[str, object]:
    _ensure_viewer_service(app_name)
    record = storage_backend.read_markdown_record(app_name, target_day)
    if record is None:
        raise HTTPException(status_code=404, detail="Markdown content not found")
    if previous_updated_at is not None and _serialize_timestamp(
        record.updated_at
    ) == _serialize_timestamp(previous_updated_at):
        raise HTTPException(status_code=404, detail="Markdown content not found")

    articles = _render_articles(
        _resolve_article_states(
            storage_backend=storage_backend,
            app_name=app_name,
            target_day=target_day,
            markdown_text=record.content,
        )
    )
    return {
        "markdown": record.content,
        "articles": [article.to_state() for article in articles],
        "updated_at": _serialize_timestamp(record.updated_at),
    }


def read_article_or_404(
    storage_backend: StorageBackend,
    app_name: str,
    target_day: date,
    article_id: str,
) -> ViewerArticleState:
    _ensure_viewer_service(app_name)
    record = storage_backend.read_markdown_record(app_name, target_day)
    if record is None:
        raise HTTPException(status_code=404, detail="Markdown content not found")

    for article in _resolve_article_states(
        storage_backend=storage_backend,
        app_name=app_name,
        target_day=target_day,
        markdown_text=record.content,
    ):
        if article.article_id == article_id:
            return article

    raise HTTPException(status_code=404, detail="Article not found")


def trigger_retry(job_invoker: JobInvoker, app_name: str) -> dict[str, str]:
    _ensure_viewer_service(app_name)
    started_at = _serialize_timestamp(datetime.now(timezone.utc))
    try:
        job_invoker.trigger(app_name)
    except Exception as error:
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Failed to trigger {app_name}: {error}",
        ) from error

    return {
        "message": f"Job trigger for {app_name} accepted. Processing started.",
        "started_at": started_at or "",
    }


def display_label(app_name: str) -> str:
    return TAB_LABELS.get(app_name, app_name)


def _ensure_viewer_service(app_name: str) -> None:
    if app_name not in viewer_service_names():
        raise HTTPException(status_code=404, detail="App not found")


def _initial_app_name(page: ViewerPage) -> str | None:
    return page.app_names[0] if page.app_names else None


def _extract_article_title(markdown_text: str, index: int) -> str:
    for line in markdown_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        heading_match = re.match(r"^#{1,6}\s+(.*)$", stripped)
        if heading_match:
            return heading_match.group(1).strip()
        return stripped[:80]
    return f"Article {index + 1}"


def _render_initial_article(
    article_state: ViewerArticleState,
    render_index: int,
) -> ViewerRenderedArticle:
    try:
        html = markdown.markdown(article_state.markdown, extensions=["extra"])
        soup = BeautifulSoup(html, "html.parser")
        _sanitize_rendered_html(soup)
        headings = _apply_heading_ids(
            soup,
            anchor_prefix=f"{article_state.article_id}-{render_index}",
        )
        return ViewerRenderedArticle(
            article_id=article_state.article_id,
            title=article_state.title,
            html=str(soup),
            headings=headings,
        )
    except Exception:
        print(traceback.format_exc())
        return ViewerRenderedArticle(
            article_id=article_state.article_id,
            title=article_state.title,
            html=f"<pre>{escape(article_state.markdown)}</pre>",
            headings=[],
        )


def _render_articles(
    article_states: list[ViewerArticleState],
) -> list[ViewerRenderedArticle]:
    return [
        _render_initial_article(article_state, render_index)
        for render_index, article_state in enumerate(article_states)
    ]


def _sanitize_rendered_html(soup: BeautifulSoup) -> None:
    dangerous_tags = {"script", "style", "iframe", "object", "embed", "link", "meta"}
    for element in list(soup.find_all(True)):
        if element.name in dangerous_tags:
            element.decompose()
            continue

        allowed_attributes = {
            "a": {"href", "title"},
            "img": {"src", "alt", "title"},
            "th": {"colspan", "rowspan"},
            "td": {"colspan", "rowspan"},
        }.get(element.name, set())
        safe_attributes: dict[str, str] = {}
        for key, value in element.attrs.items():
            if key.startswith("on") or key not in allowed_attributes:
                continue
            if isinstance(value, list):
                value = " ".join(value)
            normalized_value = value.strip() if isinstance(value, str) else ""
            lowered_value = normalized_value.lower()
            if key in {"href", "src"} and (
                lowered_value.startswith("javascript:")
                or lowered_value.startswith("data:text/html")
            ):
                continue
            safe_attributes[key] = normalized_value
        element.attrs = safe_attributes

        if element.name == "a" and "href" in element.attrs:
            element.attrs["target"] = "_blank"
            element.attrs["rel"] = "noopener noreferrer"


def _apply_heading_ids(
    soup: BeautifulSoup,
    anchor_prefix: str,
) -> list[ViewerHeading]:
    heading_counters: dict[str, int] = {}
    headings: list[ViewerHeading] = []
    for index, heading in enumerate(soup.select("h1, h2, h3")):
        base = _slugify(heading.get_text(" ", strip=True), index)
        heading_counters[base] = heading_counters.get(base, 0) + 1
        suffix = "" if heading_counters[base] == 1 else f"-{heading_counters[base]}"
        anchor = f"heading-{anchor_prefix}-{base}{suffix}"
        heading["id"] = anchor
        heading["class"] = [
            "md-heading",
            f"md-h{heading.name[1]}",
        ]
        headings.append(
            ViewerHeading(
                text=heading.get_text(" ", strip=True),
                anchor=anchor,
                level=int(heading.name[1]),
            )
        )
    return headings


def _serialize_timestamp(timestamp: datetime | None) -> str | None:
    if timestamp is None:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc).isoformat()


def _article_identity_state_key(target_day: date) -> str:
    return f"viewer-article-identity-{target_day.isoformat()}.json"


def _load_article_identity_state(raw_state: str | None) -> list[dict[str, str]]:
    if raw_state is None:
        return []

    try:
        payload = json.loads(raw_state)
        if not isinstance(payload, dict):
            raise ValueError("article identity state must be a JSON object")
        if payload.get("version") != ARTICLE_IDENTITY_STATE_VERSION:
            raise ValueError("article identity state version is unsupported")
        articles = payload.get("articles")
        if not isinstance(articles, list):
            raise ValueError("article identity state articles must be a list")

        entries: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        for entry in articles:
            if not isinstance(entry, dict):
                raise ValueError("article identity state entry must be an object")
            article_id = entry.get("article_id")
            canonical_markdown = entry.get("canonical_markdown")
            if not isinstance(article_id, str) or not article_id:
                raise ValueError("article identity state article_id must be a string")
            if not isinstance(canonical_markdown, str) or not canonical_markdown:
                raise ValueError(
                    "article identity state canonical_markdown must be a string"
                )
            if article_id in seen_ids:
                raise ValueError("article identity state article_id must be unique")
            seen_ids.add(article_id)
            entries.append(
                {
                    "article_id": article_id,
                    "canonical_markdown": canonical_markdown,
                }
            )
        return entries
    except Exception as error:
        print(traceback.format_exc())
        raise ValueError("Failed to load viewer article identity state") from error


def _serialize_article_identity_state(
    article_states: list[ViewerArticleState],
) -> str:
    return json.dumps(
        {
            "version": ARTICLE_IDENTITY_STATE_VERSION,
            "articles": [
                {
                    "article_id": article.article_id,
                    "canonical_markdown": _canonicalize_article_markdown(
                        article.markdown
                    ),
                }
                for article in article_states
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _allocate_article_id(
    app_name: str,
    canonical_markdown: str,
    used_ids: set[str],
) -> str:
    base_id = _build_article_id(
        app_name=app_name,
        markdown_text=canonical_markdown,
    )
    if base_id not in used_ids:
        return base_id

    suffix = 2
    while True:
        candidate_id = f"{base_id}-i{suffix}"
        if candidate_id not in used_ids:
            return candidate_id
        suffix += 1


def _build_article_id(
    app_name: str,
    markdown_text: str,
) -> str:
    canonical_markdown = _canonicalize_article_markdown(markdown_text)
    fingerprint = hashlib.sha256(canonical_markdown.encode("utf-8")).hexdigest()[:12]
    return f"article-{app_name}-{fingerprint}"


def _canonicalize_article_markdown(markdown_text: str) -> str:
    return "\n".join(line.rstrip() for line in markdown_text.strip().splitlines())


def _slugify(text: str, index: int) -> str:
    normalized = re.sub(
        r"[^\w\u3040-\u30ff\u3400-\u9fff\s-]",
        "",
        text.strip().lower(),
    )
    normalized = re.sub(r"\s+", "-", normalized)
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return normalized or f"section-{index}"
