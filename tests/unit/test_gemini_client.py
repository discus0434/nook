from types import SimpleNamespace

import pytest
import requests
from google.genai.errors import APIError
from pydantic import BaseModel


class DummyAPIError(APIError):
    def __init__(self) -> None:
        pass


def test_is_retryable_error_includes_api_and_network_timeouts() -> None:
    from nook.services.gemini_client import _is_retryable_error

    assert _is_retryable_error(DummyAPIError())
    assert _is_retryable_error(requests.exceptions.ReadTimeout())
    assert _is_retryable_error(requests.exceptions.ConnectionError())
    assert not _is_retryable_error(ValueError("boom"))


def test_resolve_gemini_model_uses_env_when_explicit_value_is_missing() -> None:
    from nook.services.gemini_client import resolve_gemini_model

    assert resolve_gemini_model(env={"GEMINI_MODEL": "gemini-2.5-flash"}) == (
        "gemini-2.5-flash"
    )


def test_resolve_gemini_model_raises_when_env_is_missing() -> None:
    from nook.services.gemini_client import resolve_gemini_model

    with pytest.raises(
        ValueError, match="Missing required environment variable: GEMINI_MODEL"
    ):
        resolve_gemini_model(env={})


def test_resolve_gemini_model_does_not_fall_back_to_process_env_when_env_is_explicit(
    monkeypatch,
) -> None:
    from nook.services.gemini_client import resolve_gemini_model

    monkeypatch.setenv("GEMINI_MODEL", "gemini-from-process")

    with pytest.raises(
        ValueError, match="Missing required environment variable: GEMINI_MODEL"
    ):
        resolve_gemini_model(env={})


def test_create_client_uses_env_model_as_default(monkeypatch) -> None:
    import nook.services.gemini_client as gemini_client

    class DummyGenAIClient:
        def __init__(self, *, api_key: str, http_options: object) -> None:
            self.api_key = api_key
            self.http_options = http_options

    monkeypatch.setattr(gemini_client, "require_runtime_secret", lambda key: "test-key")
    monkeypatch.setattr(gemini_client.genai, "Client", DummyGenAIClient)

    client = gemini_client.create_client(env={"GEMINI_MODEL": "gemini-2.5-flash"})

    assert client._config.model == "gemini-2.5-flash"


def test_create_client_prefers_config_model_over_env(monkeypatch) -> None:
    import nook.services.gemini_client as gemini_client

    class DummyGenAIClient:
        def __init__(self, *, api_key: str, http_options: object) -> None:
            self.api_key = api_key
            self.http_options = http_options

    monkeypatch.setattr(gemini_client, "require_runtime_secret", lambda key: "test-key")
    monkeypatch.setattr(gemini_client.genai, "Client", DummyGenAIClient)

    client = gemini_client.create_client(
        config={"model": "gemini-1.5-pro"},
        env={"GEMINI_MODEL": "gemini-2.5-flash"},
    )

    assert client._config.model == "gemini-1.5-pro"


def test_create_client_requires_env_model_even_when_config_overrides(
    monkeypatch,
) -> None:
    import nook.services.gemini_client as gemini_client

    monkeypatch.setattr(gemini_client, "require_runtime_secret", lambda key: "test-key")

    with pytest.raises(
        ValueError, match="Missing required environment variable: GEMINI_MODEL"
    ):
        gemini_client.create_client(config={"model": "gemini-1.5-pro"}, env={})


def test_create_client_prefers_explicit_model_over_env(monkeypatch) -> None:
    import nook.services.gemini_client as gemini_client

    class DummyGenAIClient:
        def __init__(self, *, api_key: str, http_options: object) -> None:
            self.api_key = api_key
            self.http_options = http_options

    monkeypatch.setattr(gemini_client, "require_runtime_secret", lambda key: "test-key")
    monkeypatch.setattr(gemini_client.genai, "Client", DummyGenAIClient)

    client = gemini_client.create_client(
        env={"GEMINI_MODEL": "gemini-2.5-flash"},
        model="gemini-2.0-pro",
    )

    assert client._config.model == "gemini-2.0-pro"


def test_create_client_requires_env_model_even_when_explicit_model_overrides(
    monkeypatch,
) -> None:
    import nook.services.gemini_client as gemini_client

    monkeypatch.setattr(gemini_client, "require_runtime_secret", lambda key: "test-key")

    with pytest.raises(
        ValueError, match="Missing required environment variable: GEMINI_MODEL"
    ):
        gemini_client.create_client(model="gemini-2.0-pro", env={})


class _StructuredResponse(BaseModel):
    summary: str
    bullets: list[str]


def _dummy_response(text: str):
    return SimpleNamespace(
        text=text,
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(parts=[SimpleNamespace(text=text)]),
            )
        ],
    )


def _dummy_response_with_parsed(text: str, parsed: object):
    response = _dummy_response(text)
    response.parsed = parsed
    return response


def test_generate_structured_content_uses_json_schema_and_validates_response(
    monkeypatch,
) -> None:
    import nook.services.gemini_client as gemini_client

    calls: dict[str, object] = {}

    class DummyModels:
        def generate_content(self, *, model: str, contents: list[str], config: object):
            calls["model"] = model
            calls["contents"] = contents
            calls["config"] = config
            return _dummy_response('{"summary":"hello","bullets":["a","b"]}')

    class DummyGenAIClient:
        def __init__(self, *, api_key: str, http_options: object) -> None:
            self.api_key = api_key
            self.http_options = http_options
            self.models = DummyModels()

    monkeypatch.setattr(gemini_client, "require_runtime_secret", lambda key: "test-key")
    monkeypatch.setattr(gemini_client.genai, "Client", DummyGenAIClient)

    client = gemini_client.create_client(env={"GEMINI_MODEL": "gemini-2.5-flash"})
    response = client.generate_structured_content(
        contents="hello",
        response_schema=_StructuredResponse,
    )

    assert response == _StructuredResponse(summary="hello", bullets=["a", "b"])
    assert calls["model"] == "gemini-2.5-flash"
    assert calls["contents"] == ["hello"]
    assert calls["config"].response_mime_type == "application/json"
    assert calls["config"].response_schema is _StructuredResponse


def test_generate_structured_content_raises_on_invalid_json(monkeypatch) -> None:
    import nook.services.gemini_client as gemini_client

    class DummyModels:
        def generate_content(self, *, model: str, contents: list[str], config: object):
            _ = model, contents, config
            return _dummy_response("not-json")

    class DummyGenAIClient:
        def __init__(self, *, api_key: str, http_options: object) -> None:
            self.models = DummyModels()

    monkeypatch.setattr(gemini_client, "require_runtime_secret", lambda key: "test-key")
    monkeypatch.setattr(gemini_client.genai, "Client", DummyGenAIClient)

    client = gemini_client.create_client(env={"GEMINI_MODEL": "gemini-2.5-flash"})

    with pytest.raises(
        ValueError,
        match="Failed to decode structured Gemini response",
    ):
        client.generate_structured_content(
            contents="hello",
            response_schema=_StructuredResponse,
        )


def test_generate_structured_content_prefers_sdk_parsed_response(
    monkeypatch,
) -> None:
    import nook.services.gemini_client as gemini_client

    class DummyModels:
        def generate_content(self, *, model: str, contents: list[str], config: object):
            _ = model, contents, config
            return _dummy_response_with_parsed(
                "not-json",
                _StructuredResponse(summary="hello", bullets=["a", "b"]),
            )

    class DummyGenAIClient:
        def __init__(self, *, api_key: str, http_options: object) -> None:
            self.models = DummyModels()

    monkeypatch.setattr(gemini_client, "require_runtime_secret", lambda key: "test-key")
    monkeypatch.setattr(gemini_client.genai, "Client", DummyGenAIClient)

    client = gemini_client.create_client(env={"GEMINI_MODEL": "gemini-2.5-flash"})

    response = client.generate_structured_content(
        contents="hello",
        response_schema=_StructuredResponse,
    )

    assert response == _StructuredResponse(summary="hello", bullets=["a", "b"])


def test_generate_structured_content_repairs_code_fence_and_trailing_comma(
    monkeypatch,
) -> None:
    import nook.services.gemini_client as gemini_client

    class DummyModels:
        def generate_content(self, *, model: str, contents: list[str], config: object):
            _ = model, contents, config
            return _dummy_response(
                """```json
{
  "summary": "hello",
  "bullets": [
    "a",
    "b"
  ],
}
```"""
            )

    class DummyGenAIClient:
        def __init__(self, *, api_key: str, http_options: object) -> None:
            self.models = DummyModels()

    monkeypatch.setattr(gemini_client, "require_runtime_secret", lambda key: "test-key")
    monkeypatch.setattr(gemini_client.genai, "Client", DummyGenAIClient)

    client = gemini_client.create_client(env={"GEMINI_MODEL": "gemini-2.5-flash"})

    response = client.generate_structured_content(
        contents="hello",
        response_schema=_StructuredResponse,
    )

    assert response == _StructuredResponse(summary="hello", bullets=["a", "b"])


def test_generate_structured_content_strips_outer_whitespace(
    monkeypatch,
) -> None:
    import nook.services.gemini_client as gemini_client

    class DummyModels:
        def generate_content(self, *, model: str, contents: list[str], config: object):
            _ = model, contents, config
            return _dummy_response('\n  {"summary":"hello","bullets":["a","b"]}  \n')

    class DummyGenAIClient:
        def __init__(self, *, api_key: str, http_options: object) -> None:
            self.models = DummyModels()

    monkeypatch.setattr(gemini_client, "require_runtime_secret", lambda key: "test-key")
    monkeypatch.setattr(gemini_client.genai, "Client", DummyGenAIClient)

    client = gemini_client.create_client(env={"GEMINI_MODEL": "gemini-2.5-flash"})

    response = client.generate_structured_content(
        contents="hello",
        response_schema=_StructuredResponse,
    )

    assert response == _StructuredResponse(summary="hello", bullets=["a", "b"])


def test_generate_structured_content_repairs_missing_comma_between_fields(
    monkeypatch,
) -> None:
    import nook.services.gemini_client as gemini_client

    class DummyModels:
        def generate_content(self, *, model: str, contents: list[str], config: object):
            _ = model, contents, config
            return _dummy_response(
                """{
  "summary": "hello"
  "bullets": [
    "a",
    "b"
  ]
}"""
            )

    class DummyGenAIClient:
        def __init__(self, *, api_key: str, http_options: object) -> None:
            self.models = DummyModels()

    monkeypatch.setattr(gemini_client, "require_runtime_secret", lambda key: "test-key")
    monkeypatch.setattr(gemini_client.genai, "Client", DummyGenAIClient)

    client = gemini_client.create_client(env={"GEMINI_MODEL": "gemini-2.5-flash"})

    response = client.generate_structured_content(
        contents="hello",
        response_schema=_StructuredResponse,
    )

    assert response == _StructuredResponse(summary="hello", bullets=["a", "b"])


def test_generate_structured_content_rejects_freeform_text_wrapped_json(
    monkeypatch, capsys
) -> None:
    import nook.services.gemini_client as gemini_client

    class DummyModels:
        def generate_content(self, *, model: str, contents: list[str], config: object):
            _ = model, contents, config
            return _dummy_response(
                'Here is the JSON you requested: {"summary":"hello","bullets":["a","b"]}'
            )

    class DummyGenAIClient:
        def __init__(self, *, api_key: str, http_options: object) -> None:
            self.models = DummyModels()

    monkeypatch.setattr(gemini_client, "require_runtime_secret", lambda key: "test-key")
    monkeypatch.setattr(gemini_client.genai, "Client", DummyGenAIClient)

    client = gemini_client.create_client(env={"GEMINI_MODEL": "gemini-2.5-flash"})

    with pytest.raises(
        ValueError,
        match="Failed to decode structured Gemini response",
    ):
        client.generate_structured_content(
            contents="hello",
            response_schema=_StructuredResponse,
        )

    captured = capsys.readouterr()
    assert "Traceback" in captured.out


def test_generate_structured_content_raises_when_repair_returns_non_object(
    monkeypatch, capsys
) -> None:
    import nook.services.gemini_client as gemini_client

    class DummyModels:
        def generate_content(self, *, model: str, contents: list[str], config: object):
            _ = model, contents, config
            return _dummy_response('{"summary":"hello","bullets":[}')

    class DummyGenAIClient:
        def __init__(self, *, api_key: str, http_options: object) -> None:
            self.models = DummyModels()

    monkeypatch.setattr(gemini_client, "require_runtime_secret", lambda key: "test-key")
    monkeypatch.setattr(gemini_client.genai, "Client", DummyGenAIClient)
    monkeypatch.setattr(gemini_client, "repair_json", lambda *args, **kwargs: ["oops"])

    client = gemini_client.create_client(env={"GEMINI_MODEL": "gemini-2.5-flash"})

    with pytest.raises(
        ValueError,
        match="Failed to decode structured Gemini response",
    ):
        client.generate_structured_content(
            contents="hello",
            response_schema=_StructuredResponse,
        )

    captured = capsys.readouterr()
    assert "Traceback" in captured.out


def test_generate_structured_content_raises_on_schema_mismatch(monkeypatch) -> None:
    import nook.services.gemini_client as gemini_client

    class DummyModels:
        def generate_content(self, *, model: str, contents: list[str], config: object):
            _ = model, contents, config
            return _dummy_response('{"summary":"hello","bullets":"not-a-list"}')

    class DummyGenAIClient:
        def __init__(self, *, api_key: str, http_options: object) -> None:
            self.models = DummyModels()

    monkeypatch.setattr(gemini_client, "require_runtime_secret", lambda key: "test-key")
    monkeypatch.setattr(gemini_client.genai, "Client", DummyGenAIClient)

    client = gemini_client.create_client(env={"GEMINI_MODEL": "gemini-2.5-flash"})

    with pytest.raises(
        ValueError,
        match="Failed to validate structured Gemini response",
    ):
        client.generate_structured_content(
            contents="hello",
            response_schema=_StructuredResponse,
        )
