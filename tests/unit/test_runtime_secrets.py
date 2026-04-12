import json

import pytest


class FakeSecretsManagerClient:
    def __init__(self, payloads: dict[str, dict[str, str]] | None = None) -> None:
        self.payloads = payloads or {}
        self.requested: list[str] = []

    def get_secret_value(self, *, SecretId: str) -> dict[str, str]:
        self.requested.append(SecretId)
        payload = self.payloads[SecretId]
        return {"SecretString": json.dumps(payload)}


def test_get_runtime_secret_prefers_direct_env_values() -> None:
    from nook.services.runtime_secrets import RuntimeSecretsCache, get_runtime_secret

    value = get_runtime_secret(
        "OPENAI_API_KEY",
        env={
            "OPENAI_API_KEY": "direct-value",
            "NOOK_AWS_SECRET_ID": "my-nook/runtime-secrets",
        },
        secrets_client=FakeSecretsManagerClient(
            {"my-nook/runtime-secrets": {"OPENAI_API_KEY": "aws-value"}}
        ),
        cache=RuntimeSecretsCache(),
    )

    assert value == "direct-value"


def test_get_runtime_secret_reads_and_caches_aws_secret_json() -> None:
    from nook.services.runtime_secrets import RuntimeSecretsCache, get_runtime_secret

    client = FakeSecretsManagerClient(
        {
            "my-nook/runtime-secrets": {
                "OPENAI_API_KEY": "aws-value",
                "REDDIT_CLIENT_ID": "reddit-client",
            }
        }
    )
    cache = RuntimeSecretsCache()

    openai = get_runtime_secret(
        "OPENAI_API_KEY",
        env={"NOOK_AWS_SECRET_ID": "my-nook/runtime-secrets"},
        secrets_client=client,
        cache=cache,
    )
    reddit = get_runtime_secret(
        "REDDIT_CLIENT_ID",
        env={"NOOK_AWS_SECRET_ID": "my-nook/runtime-secrets"},
        secrets_client=client,
        cache=cache,
    )

    assert openai == "aws-value"
    assert reddit == "reddit-client"
    assert client.requested == ["my-nook/runtime-secrets"]


def test_require_runtime_secret_raises_when_key_is_missing() -> None:
    from nook.services.runtime_secrets import (
        RuntimeSecretsCache,
        require_runtime_secret,
    )

    with pytest.raises(ValueError, match="Missing runtime secret: OPENAI_API_KEY"):
        require_runtime_secret(
            "OPENAI_API_KEY",
            env={"NOOK_AWS_SECRET_ID": "my-nook/runtime-secrets"},
            secrets_client=FakeSecretsManagerClient(
                {"my-nook/runtime-secrets": {"REDDIT_CLIENT_ID": "reddit-client"}}
            ),
            cache=RuntimeSecretsCache(),
        )


def test_is_runtime_secret_key_accepts_generic_api_keys() -> None:
    from nook.services.runtime_secrets import is_runtime_secret_key

    assert is_runtime_secret_key("OPENAI_API_KEY") is True
    assert is_runtime_secret_key("GOOGLE_API_KEY") is True
    assert is_runtime_secret_key("REDDIT_CLIENT_ID") is True
    assert is_runtime_secret_key("LLM_MODEL") is False


def test_export_runtime_secrets_to_env_merges_cached_secret_payload() -> None:
    from nook.services.runtime_secrets import (
        RuntimeSecretsCache,
        export_runtime_secrets_to_env,
    )

    target_env = {"EXISTING": "keep"}
    export_runtime_secrets_to_env(
        target_env=target_env,
        env={"NOOK_AWS_SECRET_ID": "my-nook/runtime-secrets"},
        secrets_client=FakeSecretsManagerClient(
            {
                "my-nook/runtime-secrets": {
                    "OPENAI_API_KEY": "aws-openai",
                    "REDDIT_CLIENT_ID": "reddit-client",
                }
            }
        ),
        cache=RuntimeSecretsCache(),
    )

    assert target_env["EXISTING"] == "keep"
    assert target_env["OPENAI_API_KEY"] == "aws-openai"
    assert target_env["REDDIT_CLIENT_ID"] == "reddit-client"


def test_export_runtime_secrets_to_env_does_not_fall_back_to_process_env_when_env_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nook.services.runtime_secrets import export_runtime_secrets_to_env

    monkeypatch.setenv("OPENAI_API_KEY", "process-openai")

    target_env: dict[str, str] = {}
    export_runtime_secrets_to_env(target_env=target_env, env={})

    assert "OPENAI_API_KEY" not in target_env
