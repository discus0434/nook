import json
import os
from dataclasses import dataclass, field
from typing import Mapping

import boto3

AWS_RUNTIME_SECRET_ID_ENV = "NOOK_AWS_SECRET_ID"
DEFAULT_AWS_RUNTIME_SECRET_ID = "my-nook/runtime-secrets"
RUNTIME_SECRET_KEYS = (
    "GEMINI_API_KEY",
    "REDDIT_CLIENT_ID",
    "REDDIT_CLIENT_SECRET",
    "REDDIT_USER_AGENT",
    "PRODUCT_HUNT_API_KEY",
    "PRODUCT_HUNT_DEVELOPER_TOKEN",
)


@dataclass(slots=True)
class RuntimeSecretsCache:
    payloads: dict[str, dict[str, str]] = field(default_factory=dict)


_DEFAULT_CACHE = RuntimeSecretsCache()


def get_runtime_secret(
    secret_key: str,
    *,
    env: Mapping[str, str | None] | None = None,
    secrets_client: object | None = None,
    cache: RuntimeSecretsCache | None = None,
) -> str | None:
    resolved_env = env or os.environ
    direct_value = resolved_env.get(secret_key)
    if direct_value:
        return direct_value

    secret_id = resolved_env.get(AWS_RUNTIME_SECRET_ID_ENV)
    if not secret_id:
        return None

    payload = _load_runtime_secret_payload(
        secret_id=secret_id,
        secrets_client=secrets_client,
        cache=cache or _DEFAULT_CACHE,
    )
    return payload.get(secret_key)


def require_runtime_secret(
    secret_key: str,
    *,
    env: Mapping[str, str | None] | None = None,
    secrets_client: object | None = None,
    cache: RuntimeSecretsCache | None = None,
) -> str:
    value = get_runtime_secret(
        secret_key,
        env=env,
        secrets_client=secrets_client,
        cache=cache,
    )
    if not value:
        raise ValueError(f"Missing runtime secret: {secret_key}")
    return value


def _load_runtime_secret_payload(
    *,
    secret_id: str,
    secrets_client: object | None,
    cache: RuntimeSecretsCache,
) -> dict[str, str]:
    if secret_id in cache.payloads:
        return cache.payloads[secret_id]

    client = secrets_client or boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=secret_id)
    secret_string = response.get("SecretString")
    if not secret_string:
        raise ValueError(f"Secret {secret_id} does not contain SecretString")

    payload = json.loads(secret_string)
    if not isinstance(payload, dict):
        raise ValueError(f"Secret {secret_id} must contain a JSON object")

    normalized_payload = {
        key: value
        for key, value in payload.items()
        if isinstance(key, str) and isinstance(value, str) and value
    }
    cache.payloads[secret_id] = normalized_payload
    return normalized_payload
