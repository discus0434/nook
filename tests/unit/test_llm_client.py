import asyncio
import threading
from types import SimpleNamespace

import httpx
import pytest
from pydantic import BaseModel


class _StructuredResponse(BaseModel):
    summary: str
    bullets: list[str]


def test_is_retryable_error_includes_network_timeouts() -> None:
    from nook.services.llm_client import _is_retryable_error

    assert _is_retryable_error(httpx.ReadTimeout("timeout"))
    assert _is_retryable_error(httpx.ConnectError("connect", request=None))
    assert not _is_retryable_error(ValueError("boom"))


def test_resolve_llm_model_uses_env_when_explicit_value_is_missing() -> None:
    from nook.services.llm_client import resolve_llm_model

    assert resolve_llm_model(env={"LLM_MODEL": "openai:gpt-5.2"}) == "openai:gpt-5.2"


def test_resolve_llm_model_raises_when_env_is_missing() -> None:
    from nook.services.llm_client import resolve_llm_model

    with pytest.raises(
        ValueError, match="Missing required environment variable: LLM_MODEL"
    ):
        resolve_llm_model(env={})


def test_resolve_llm_model_does_not_fall_back_to_process_env_when_env_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nook.services.llm_client import resolve_llm_model

    monkeypatch.setenv("LLM_MODEL", "openai:gpt-5.2")

    with pytest.raises(
        ValueError, match="Missing required environment variable: LLM_MODEL"
    ):
        resolve_llm_model(env={})


def test_create_client_uses_env_model_as_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nook.services.llm_client as llm_client

    monkeypatch.setattr(
        llm_client,
        "export_runtime_secrets_to_env",
        lambda **kwargs: None,
    )

    client = llm_client.create_client(env={"LLM_MODEL": "openai:gpt-5.2"})

    assert client._config.model == "openai:gpt-5.2"


def test_create_client_prefers_config_model_over_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nook.services.llm_client as llm_client

    monkeypatch.setattr(
        llm_client,
        "export_runtime_secrets_to_env",
        lambda **kwargs: None,
    )

    client = llm_client.create_client(
        config={"model": "anthropic:claude-sonnet-4-5"},
        env={"LLM_MODEL": "openai:gpt-5.2"},
    )

    assert client._config.model == "anthropic:claude-sonnet-4-5"


def test_create_client_requires_env_model_even_when_config_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nook.services.llm_client as llm_client

    monkeypatch.setattr(
        llm_client,
        "export_runtime_secrets_to_env",
        lambda **kwargs: None,
    )

    with pytest.raises(
        ValueError, match="Missing required environment variable: LLM_MODEL"
    ):
        llm_client.create_client(config={"model": "openai:gpt-5.2"}, env={})


def test_create_client_exports_runtime_secrets_to_process_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nook.services.llm_client as llm_client

    captured: dict[str, object] = {}

    def fake_export_runtime_secrets_to_env(**kwargs) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(
        llm_client,
        "export_runtime_secrets_to_env",
        fake_export_runtime_secrets_to_env,
    )

    llm_client.create_client(env={"LLM_MODEL": "openai:gpt-5.2"})

    assert captured["env"] == {"LLM_MODEL": "openai:gpt-5.2"}


def test_generate_content_uses_agent_run_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    import nook.services.llm_client as llm_client

    calls: dict[str, object] = {}

    class DummyAgent:
        def __init__(
            self,
            model: str,
            *,
            instructions: str | None = None,
            output_type: object = str,
            model_settings: object = None,
            tools: list[object] | None = None,
        ) -> None:
            calls["model"] = model
            calls["instructions"] = instructions
            calls["output_type"] = output_type
            calls["model_settings"] = model_settings
            calls["tools"] = tools or []

        def run_sync(self, prompt: str) -> SimpleNamespace:
            calls["prompt"] = prompt
            return SimpleNamespace(output="hello")

    monkeypatch.setattr(
        llm_client,
        "export_runtime_secrets_to_env",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(llm_client, "Agent", DummyAgent)

    client = llm_client.create_client(env={"LLM_MODEL": "openai:gpt-5.2"})
    response = client.generate_content(
        contents="hello",
        system_instruction="be concise",
    )

    assert response == "hello"
    assert calls["model"] == "openai:gpt-5.2"
    assert calls["instructions"] == "be concise"
    assert calls["output_type"] is str
    assert calls["prompt"] == "hello"


def test_generate_structured_content_uses_output_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nook.services.llm_client as llm_client

    calls: dict[str, object] = {}

    class DummyAgent:
        def __init__(
            self,
            model: str,
            *,
            instructions: str | None = None,
            output_type: object = str,
            model_settings: object = None,
            tools: list[object] | None = None,
        ) -> None:
            calls["model"] = model
            calls["instructions"] = instructions
            calls["output_type"] = output_type
            calls["model_settings"] = model_settings
            calls["tools"] = tools or []

        def run_sync(self, prompt: str) -> SimpleNamespace:
            calls["prompt"] = prompt
            return SimpleNamespace(
                output=_StructuredResponse(summary="hello", bullets=["a", "b"])
            )

    monkeypatch.setattr(
        llm_client,
        "export_runtime_secrets_to_env",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(llm_client, "Agent", DummyAgent)

    client = llm_client.create_client(env={"LLM_MODEL": "openai:gpt-5.2"})
    response = client.generate_structured_content(
        contents="hello",
        response_schema=_StructuredResponse,
        system_instruction="return json",
    )

    assert response == _StructuredResponse(summary="hello", bullets=["a", "b"])
    assert calls["model"] == "openai:gpt-5.2"
    assert calls["instructions"] == "return json"
    assert calls["output_type"] is _StructuredResponse
    assert calls["prompt"] == "hello"


def test_generate_content_uses_dedicated_google_client_and_closes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nook.services.llm_client as llm_client

    captured: dict[str, object] = {}

    class DummyAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            captured["async_client_kwargs"] = kwargs
            self.is_closed = False

        async def aclose(self) -> None:
            self.is_closed = True
            captured["closed"] = True

    class DummyGoogleProvider:
        def __init__(
            self, *, vertexai: bool = False, http_client: object | None = None
        ):
            captured["provider_vertexai"] = vertexai
            captured["provider_http_client"] = http_client

    class DummyGoogleModel:
        def __init__(self, model_name: str, *, provider: object) -> None:
            captured["google_model_name"] = model_name
            captured["google_model_provider"] = provider

    class DummyAgent:
        def __init__(
            self,
            model: object,
            *,
            instructions: str | None = None,
            output_type: object = str,
            model_settings: object = None,
            tools: list[object] | None = None,
            builtin_tools: list[object] | None = None,
        ) -> None:
            captured["agent_model"] = model
            captured["instructions"] = instructions
            captured["output_type"] = output_type
            captured["model_settings"] = model_settings
            captured["tools"] = tools or []
            captured["builtin_tools"] = builtin_tools or []

        def run_sync(self, prompt: str) -> SimpleNamespace:
            captured["prompt"] = prompt
            return SimpleNamespace(output="hello")

    monkeypatch.setattr(
        llm_client,
        "export_runtime_secrets_to_env",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(llm_client.httpx, "AsyncClient", DummyAsyncClient)
    monkeypatch.setattr(
        llm_client, "GoogleProvider", DummyGoogleProvider, raising=False
    )
    monkeypatch.setattr(llm_client, "GoogleModel", DummyGoogleModel, raising=False)
    monkeypatch.setattr(llm_client, "Agent", DummyAgent)

    client = llm_client.create_client(env={"LLM_MODEL": "google-gla:gemini-test"})
    response = client.generate_content("hello")

    assert response == "hello"
    assert captured["google_model_name"] == "gemini-test"
    assert captured["provider_vertexai"] is False
    assert captured["provider_http_client"].__class__ is DummyAsyncClient
    assert captured["agent_model"].__class__ is DummyGoogleModel
    assert captured["closed"] is True


def test_generate_content_closes_dedicated_google_client_when_agent_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nook.services.llm_client as llm_client

    captured: dict[str, object] = {}

    class DummyAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            captured["async_client_kwargs"] = kwargs

        async def aclose(self) -> None:
            captured["closed"] = True

    class DummyGoogleProvider:
        def __init__(
            self, *, vertexai: bool = False, http_client: object | None = None
        ):
            captured["provider_vertexai"] = vertexai
            captured["provider_http_client"] = http_client

    class DummyGoogleModel:
        def __init__(self, model_name: str, *, provider: object) -> None:
            captured["google_model_name"] = model_name
            captured["google_model_provider"] = provider

    class DummyAgent:
        def __init__(
            self,
            model: object,
            *,
            instructions: str | None = None,
            output_type: object = str,
            model_settings: object = None,
            tools: list[object] | None = None,
            builtin_tools: list[object] | None = None,
        ) -> None:
            captured["agent_model"] = model

        def run_sync(self, prompt: str) -> SimpleNamespace:
            raise RuntimeError("boom")

    monkeypatch.setattr(
        llm_client,
        "export_runtime_secrets_to_env",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(llm_client.httpx, "AsyncClient", DummyAsyncClient)
    monkeypatch.setattr(
        llm_client, "GoogleProvider", DummyGoogleProvider, raising=False
    )
    monkeypatch.setattr(llm_client, "GoogleModel", DummyGoogleModel, raising=False)
    monkeypatch.setattr(llm_client, "Agent", DummyAgent)

    client = llm_client.create_client(env={"LLM_MODEL": "google-gla:gemini-test"})

    with pytest.raises(RuntimeError, match="boom"):
        client.generate_content("hello")

    assert captured["google_model_name"] == "gemini-test"
    assert captured["closed"] is True


def test_generate_content_reraises_when_dedicated_google_client_close_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nook.services.llm_client as llm_client

    captured: dict[str, object] = {"log_messages": []}

    class DummyAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            captured["async_client_kwargs"] = kwargs

        async def aclose(self) -> None:
            raise RuntimeError("close failed")

    class DummyGoogleProvider:
        def __init__(
            self, *, vertexai: bool = False, http_client: object | None = None
        ):
            captured["provider_vertexai"] = vertexai
            captured["provider_http_client"] = http_client

    class DummyGoogleModel:
        def __init__(self, model_name: str, *, provider: object) -> None:
            captured["google_model_name"] = model_name
            captured["google_model_provider"] = provider

    class DummyAgent:
        def __init__(
            self,
            model: object,
            *,
            instructions: str | None = None,
            output_type: object = str,
            model_settings: object = None,
            tools: list[object] | None = None,
            builtin_tools: list[object] | None = None,
        ) -> None:
            captured["agent_model"] = model

        def run_sync(self, prompt: str) -> SimpleNamespace:
            return SimpleNamespace(output="hello")

    monkeypatch.setattr(
        llm_client,
        "export_runtime_secrets_to_env",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(llm_client.httpx, "AsyncClient", DummyAsyncClient)
    monkeypatch.setattr(
        llm_client, "GoogleProvider", DummyGoogleProvider, raising=False
    )
    monkeypatch.setattr(llm_client, "GoogleModel", DummyGoogleModel, raising=False)
    monkeypatch.setattr(llm_client, "Agent", DummyAgent)
    monkeypatch.setattr(
        llm_client.logger,
        "exception",
        lambda message: captured["log_messages"].append(message),
    )

    client = llm_client.create_client(env={"LLM_MODEL": "google-gla:gemini-test"})

    with pytest.raises(RuntimeError, match="close failed"):
        client.generate_content("hello")

    assert captured["google_model_name"] == "gemini-test"
    assert captured["log_messages"] == [
        "failed to close dedicated google async client",
        "llm text generation failed",
    ]


def test_generate_content_uses_worker_thread_when_event_loop_is_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nook.services.llm_client as llm_client

    captured: dict[str, object] = {}

    class DummyAgent:
        def __init__(
            self,
            model: object,
            *,
            instructions: str | None = None,
            output_type: object = str,
            model_settings: object = None,
            tools: list[object] | None = None,
            builtin_tools: list[object] | None = None,
        ) -> None:
            captured["model"] = model

        def run_sync(self, prompt: str) -> SimpleNamespace:
            captured["run_sync_thread_id"] = threading.get_ident()
            captured["prompt"] = prompt
            return SimpleNamespace(output="hello")

    monkeypatch.setattr(
        llm_client,
        "export_runtime_secrets_to_env",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(llm_client, "Agent", DummyAgent)

    client = llm_client.create_client(env={"LLM_MODEL": "openai:gpt-5.2"})

    async def invoke_generate_content() -> str:
        captured["caller_thread_id"] = threading.get_ident()
        return client.generate_content("hello")

    response = asyncio.run(invoke_generate_content())

    assert response == "hello"
    assert captured["prompt"] == "hello"
    assert captured["run_sync_thread_id"] != captured["caller_thread_id"]


def test_chat_with_search_adds_builtin_web_search_tool_for_supported_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nook.services.llm_client as llm_client

    calls: dict[str, object] = {}

    class DummyAgent:
        def __init__(
            self,
            model: str,
            *,
            instructions: str | None = None,
            output_type: object = str,
            model_settings: object = None,
            tools: list[object] | None = None,
            builtin_tools: list[object] | None = None,
        ) -> None:
            calls["model"] = model
            calls["instructions"] = instructions
            calls["output_type"] = output_type
            calls["tools"] = tools or []
            calls["builtin_tools"] = builtin_tools or []

        def run_sync(self, prompt: str) -> SimpleNamespace:
            calls["prompt"] = prompt
            return SimpleNamespace(output="searched")

    def fake_web_search_tool() -> str:
        calls["search_tool_created"] = True
        return "builtin-web-search-tool"

    monkeypatch.setattr(
        llm_client,
        "export_runtime_secrets_to_env",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(llm_client, "Agent", DummyAgent)
    monkeypatch.setattr(
        llm_client,
        "WebSearchTool",
        fake_web_search_tool,
        raising=False,
    )

    client = llm_client.create_client(
        env={"LLM_MODEL": "openai-responses:gpt-5.2"},
        use_search=True,
    )
    response = client.chat_with_search("search this")

    assert response == "searched"
    assert calls["model"] == "openai-responses:gpt-5.2"
    assert calls["output_type"] is str
    assert calls["tools"] == []
    assert calls["builtin_tools"] == ["builtin-web-search-tool"]
    assert calls["prompt"] == "search this"
    assert calls["search_tool_created"] is True


def test_chat_with_search_skips_builtin_web_search_for_unsupported_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nook.services.llm_client as llm_client

    calls: dict[str, object] = {}

    class DummyAgent:
        def __init__(
            self,
            model: str,
            *,
            instructions: str | None = None,
            output_type: object = str,
            model_settings: object = None,
            tools: list[object] | None = None,
            builtin_tools: list[object] | None = None,
        ) -> None:
            calls["model"] = model
            calls["instructions"] = instructions
            calls["output_type"] = output_type
            calls["tools"] = tools or []
            calls["builtin_tools"] = builtin_tools or []

        def run_sync(self, prompt: str) -> SimpleNamespace:
            calls["prompt"] = prompt
            return SimpleNamespace(output="searched")

    def fake_web_search_tool() -> str:
        calls["search_tool_created"] = True
        return "builtin-web-search-tool"

    monkeypatch.setattr(
        llm_client,
        "export_runtime_secrets_to_env",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(llm_client, "Agent", DummyAgent)
    monkeypatch.setattr(
        llm_client,
        "WebSearchTool",
        fake_web_search_tool,
        raising=False,
    )

    client = llm_client.create_client(
        env={"LLM_MODEL": "openai:gpt-5.2"},
        use_search=True,
    )
    response = client.chat_with_search("search this")

    assert response == "searched"
    assert calls["model"] == "openai:gpt-5.2"
    assert calls["tools"] == []
    assert calls["builtin_tools"] == []
    assert "search_tool_created" not in calls
