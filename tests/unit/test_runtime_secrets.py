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
        "GEMINI_API_KEY",
        env={
            "GEMINI_API_KEY": "direct-value",
            "NOOK_AWS_SECRET_ID": "my-nook/runtime-secrets",
        },
        secrets_client=FakeSecretsManagerClient(
            {"my-nook/runtime-secrets": {"GEMINI_API_KEY": "aws-value"}}
        ),
        cache=RuntimeSecretsCache(),
    )

    assert value == "direct-value"


def test_get_runtime_secret_reads_and_caches_aws_secret_json() -> None:
    from nook.services.runtime_secrets import RuntimeSecretsCache, get_runtime_secret

    client = FakeSecretsManagerClient(
        {
            "my-nook/runtime-secrets": {
                "GEMINI_API_KEY": "aws-value",
                "REDDIT_CLIENT_ID": "reddit-client",
            }
        }
    )
    cache = RuntimeSecretsCache()

    gemini = get_runtime_secret(
        "GEMINI_API_KEY",
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

    assert gemini == "aws-value"
    assert reddit == "reddit-client"
    assert client.requested == ["my-nook/runtime-secrets"]


def test_require_runtime_secret_raises_when_key_is_missing() -> None:
    from nook.services.runtime_secrets import (
        RuntimeSecretsCache,
        require_runtime_secret,
    )

    with pytest.raises(ValueError, match="Missing runtime secret: GEMINI_API_KEY"):
        require_runtime_secret(
            "GEMINI_API_KEY",
            env={"NOOK_AWS_SECRET_ID": "my-nook/runtime-secrets"},
            secrets_client=FakeSecretsManagerClient(
                {"my-nook/runtime-secrets": {"REDDIT_CLIENT_ID": "reddit-client"}}
            ),
            cache=RuntimeSecretsCache(),
        )
