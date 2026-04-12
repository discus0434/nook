import asyncio
import concurrent.futures
import logging
import os
import traceback
from dataclasses import dataclass
from typing import Any, Mapping, TypeVar

import httpx
from pydantic import BaseModel
from pydantic_ai import Agent, WebSearchTool
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.settings import ModelSettings
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from nook.services.runtime_secrets import export_runtime_secrets_to_env

logger = logging.getLogger(__name__)

LLM_MODEL_ENV = "LLM_MODEL"
StructuredResponseT = TypeVar("StructuredResponseT", bound=BaseModel)
_RETRYABLE_HTTP_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.NetworkError,
)
_RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}
_BUILTIN_WEB_SEARCH_PROVIDERS = frozenset(
    {
        "anthropic",
        "google",
        "google-gla",
        "google-vertex",
        "groq",
        "openai-responses",
        "openrouter",
        "xai",
    }
)


def _log_retry_attempt(retry_state) -> None:
    exception = retry_state.outcome.exception()
    attempt = retry_state.attempt_number
    wait_time = retry_state.next_action.sleep

    logger.warning(
        "llm request failed; retrying",
        extra={
            "attempt": attempt,
            "wait_seconds": wait_time,
            "error_type": type(exception).__name__ if exception else None,
        },
    )


def _is_retryable_error(error: Exception) -> bool:
    if isinstance(error, _RETRYABLE_HTTP_EXCEPTIONS):
        return True
    if isinstance(error, ModelHTTPError):
        return error.status_code in _RETRYABLE_STATUS_CODES
    return False


@dataclass
class LlmClientConfig:
    model: str
    temperature: float = 0.5
    top_p: float = 0.95
    max_output_tokens: int = 8192
    timeout: int = 60000
    use_search: bool = False

    def update(self, **kwargs) -> None:
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
            else:
                raise ValueError(f"Invalid configuration key: {key}")


@dataclass(frozen=True, slots=True)
class _PreparedModel:
    name: str
    agent_model: Any
    async_client: httpx.AsyncClient | None = None


class LlmClient:
    def __init__(
        self,
        config: LlmClientConfig,
        *,
        env: Mapping[str, str | None] | None = None,
        secrets_client: object | None = None,
        cache: object | None = None,
    ) -> None:
        export_runtime_secrets_to_env(
            target_env=os.environ,
            env=env,
            secrets_client=secrets_client,
            cache=cache,
        )
        self._config = config

    @retry(
        stop=stop_after_attempt(7),
        wait=wait_exponential(multiplier=3, min=15, max=120),
        retry=retry_if_exception(_is_retryable_error),
        before_sleep=_log_retry_attempt,
    )
    def generate_content(
        self,
        contents: str | list[str],
        system_instruction: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        max_output_tokens: int | None = None,
    ) -> str:
        try:
            output = self._run_agent(
                contents=contents,
                output_type=str,
                instructions=system_instruction,
                model=model,
                temperature=temperature,
                top_p=top_p,
                max_output_tokens=max_output_tokens,
            )
            if not isinstance(output, str) or not output:
                raise ValueError("LLM response did not contain text")
            return output
        except Exception:
            logger.exception("llm text generation failed")
            raise

    @retry(
        stop=stop_after_attempt(7),
        wait=wait_exponential(multiplier=3, min=15, max=120),
        retry=retry_if_exception(_is_retryable_error),
        before_sleep=_log_retry_attempt,
    )
    def generate_structured_content(
        self,
        contents: str | list[str],
        response_schema: type[StructuredResponseT],
        system_instruction: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        max_output_tokens: int | None = None,
    ) -> StructuredResponseT:
        try:
            output = self._run_agent(
                contents=contents,
                output_type=response_schema,
                instructions=system_instruction,
                model=model,
                temperature=temperature,
                top_p=top_p,
                max_output_tokens=max_output_tokens,
            )
            return response_schema.model_validate(output)
        except Exception:
            logger.exception("llm structured generation failed")
            raise

    @retry(
        stop=stop_after_attempt(7),
        wait=wait_exponential(multiplier=3, min=15, max=120),
        retry=retry_if_exception(_is_retryable_error),
        before_sleep=_log_retry_attempt,
    )
    def chat_with_search(self, message: str, model: str | None = None) -> str:
        try:
            output = self._run_agent(
                contents=message,
                output_type=str,
                model=model,
                use_search=True,
            )
            if not isinstance(output, str) or not output:
                raise ValueError("LLM response did not contain text")
            return output
        except Exception:
            logger.exception("llm chat_with_search failed")
            raise

    def _run_agent(
        self,
        *,
        contents: str | list[str],
        output_type: type[StructuredResponseT] | type[str],
        instructions: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        max_output_tokens: int | None = None,
        use_search: bool = False,
    ) -> Any:
        if _has_running_event_loop():
            return self._run_agent_in_worker_thread(
                contents=contents,
                output_type=output_type,
                instructions=instructions,
                model=model,
                temperature=temperature,
                top_p=top_p,
                max_output_tokens=max_output_tokens,
                use_search=use_search,
            )
        return self._execute_agent(
            contents=contents,
            output_type=output_type,
            instructions=instructions,
            model=model,
            temperature=temperature,
            top_p=top_p,
            max_output_tokens=max_output_tokens,
            use_search=use_search,
        )

    def _run_agent_in_worker_thread(
        self,
        *,
        contents: str | list[str],
        output_type: type[StructuredResponseT] | type[str],
        instructions: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        max_output_tokens: int | None = None,
        use_search: bool = False,
    ) -> Any:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                self._execute_agent,
                contents=contents,
                output_type=output_type,
                instructions=instructions,
                model=model,
                temperature=temperature,
                top_p=top_p,
                max_output_tokens=max_output_tokens,
                use_search=use_search,
            )
            return future.result()

    def _execute_agent(
        self,
        *,
        contents: str | list[str],
        output_type: type[StructuredResponseT] | type[str],
        instructions: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        max_output_tokens: int | None = None,
        use_search: bool = False,
    ) -> Any:
        prepared_model = self._prepare_model(model or self._config.model)
        try:
            agent = self._build_agent(
                output_type=output_type,
                instructions=instructions,
                model=prepared_model.agent_model,
                model_name=prepared_model.name,
                temperature=temperature,
                top_p=top_p,
                max_output_tokens=max_output_tokens,
                use_search=use_search,
            )
            result = agent.run_sync(self._normalize_prompt(contents))
            return result.output
        finally:
            self._close_prepared_model(prepared_model)

    def _build_agent(
        self,
        *,
        output_type: type[StructuredResponseT] | type[str],
        instructions: str | None = None,
        model: Any,
        model_name: str,
        temperature: float | None = None,
        top_p: float | None = None,
        max_output_tokens: int | None = None,
        use_search: bool = False,
    ) -> Agent:
        agent_kwargs: dict[str, Any] = {
            "model": model,
            "output_type": output_type,
            "instructions": instructions,
            "model_settings": self._build_model_settings(
                temperature=temperature,
                top_p=top_p,
                max_output_tokens=max_output_tokens,
            ),
        }
        builtin_tools = self._build_builtin_web_search_tools(
            model_name=model_name,
            use_search=use_search,
        )
        if builtin_tools:
            agent_kwargs["builtin_tools"] = builtin_tools

        return Agent(
            **agent_kwargs,
        )

    def _prepare_model(self, model_name: str) -> _PreparedModel:
        if not _uses_dedicated_google_client(model_name):
            return _PreparedModel(name=model_name, agent_model=model_name)

        provider_name, google_model_name = _split_provider_model_name(model_name)
        async_client = httpx.AsyncClient(timeout=self._config.timeout / 1000)
        provider = GoogleProvider(
            vertexai=provider_name == "google-vertex",
            http_client=async_client,
        )
        return _PreparedModel(
            name=model_name,
            agent_model=GoogleModel(google_model_name, provider=provider),
            async_client=async_client,
        )

    def _close_prepared_model(self, prepared_model: _PreparedModel) -> None:
        if prepared_model.async_client is None:
            return
        if getattr(prepared_model.async_client, "is_closed", False):
            return

        try:
            event_loop = _get_or_create_event_loop()
            if event_loop.is_running():
                raise RuntimeError(
                    "Cannot close dedicated Google async client while event loop is running"
                )
            event_loop.run_until_complete(prepared_model.async_client.aclose())
        except Exception:
            logger.exception("failed to close dedicated google async client")
            raise

    def _build_builtin_web_search_tools(
        self,
        *,
        model_name: str,
        use_search: bool,
    ) -> list[WebSearchTool]:
        if not (use_search or self._config.use_search):
            return []
        if not _supports_builtin_web_search(model_name):
            return []
        return [WebSearchTool()]

    def _build_model_settings(
        self,
        *,
        temperature: float | None = None,
        top_p: float | None = None,
        max_output_tokens: int | None = None,
    ) -> ModelSettings:
        return {
            "temperature": self._config.temperature
            if temperature is None
            else temperature,
            "top_p": self._config.top_p if top_p is None else top_p,
            "max_tokens": self._config.max_output_tokens
            if max_output_tokens is None
            else max_output_tokens,
            "timeout": self._config.timeout / 1000,
        }

    @staticmethod
    def _normalize_prompt(contents: str | list[str]) -> str | list[str]:
        return contents


def _supports_builtin_web_search(model_name: str) -> bool:
    return _model_provider(model_name) in _BUILTIN_WEB_SEARCH_PROVIDERS


def _uses_dedicated_google_client(model_name: str) -> bool:
    return _model_provider(model_name) in {"google-gla", "google-vertex"}


def _model_provider(model_name: str) -> str:
    return model_name.split(":", 1)[0].split("/")[-1]


def _split_provider_model_name(model_name: str) -> tuple[str, str]:
    try:
        provider_name, resolved_model_name = model_name.split(":", 1)
    except ValueError as error:
        raise ValueError(
            f"Google model must include a provider prefix and model name: {model_name}"
        ) from error

    if not resolved_model_name:
        raise ValueError(f"Google model name is empty: {model_name}")
    return provider_name, resolved_model_name


def _get_or_create_event_loop() -> asyncio.AbstractEventLoop:
    try:
        event_loop = asyncio.get_event_loop()
    except RuntimeError:
        event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(event_loop)

    if event_loop.is_closed():
        event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(event_loop)
    return event_loop


def _has_running_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def create_client(config: dict[str, Any] | None = None, **kwargs) -> LlmClient:
    env = kwargs.pop("env", None)
    secrets_client = kwargs.pop("secrets_client", None)
    cache = kwargs.pop("cache", None)
    env_model = resolve_llm_model(env=env)
    explicit_model = kwargs.pop("model", None)

    if config:
        client_config = LlmClientConfig(
            model=explicit_model or config.get("model", env_model),
            temperature=config.get("temperature", 0.5),
            top_p=config.get("top_p", 0.95),
            max_output_tokens=config.get("max_output_tokens", 8192),
            timeout=config.get("timeout", 60000),
            use_search=config.get("use_search", False),
        )
    else:
        client_config = LlmClientConfig(
            model=explicit_model or env_model,
        )

    client_config.update(**kwargs)
    return LlmClient(
        client_config,
        env=env,
        secrets_client=secrets_client,
        cache=cache,
    )


def resolve_llm_model(
    *,
    env: Mapping[str, str | None] | None = None,
) -> str:
    resolved_env = env if env is not None else os.environ
    model = resolved_env.get(LLM_MODEL_ENV)
    if model:
        return model

    try:
        raise ValueError(f"Missing required environment variable: {LLM_MODEL_ENV}")
    except ValueError:
        print(traceback.format_exc())
        raise
