import json
import traceback
from typing import Mapping

import boto3
from botocore.exceptions import ClientError

from nook.services.runtime_secrets import (
    AWS_RUNTIME_SECRET_ID_ENV,
    DEFAULT_AWS_RUNTIME_SECRET_ID,
    is_runtime_secret_key,
)


def build_secret_payload(env: Mapping[str, str | None]) -> dict[str, str]:
    return {
        key: value for key, value in env.items() if value and is_runtime_secret_key(key)
    }


def upsert_runtime_secret(
    *,
    env: Mapping[str, str | None],
    secrets_client: object | None = None,
) -> str:
    secret_id = env.get(AWS_RUNTIME_SECRET_ID_ENV) or DEFAULT_AWS_RUNTIME_SECRET_ID
    payload = build_secret_payload(env)
    if not payload:
        return secret_id

    serialized_payload = json.dumps(payload, sort_keys=True)
    client = secrets_client or boto3.client("secretsmanager")

    try:
        client.describe_secret(SecretId=secret_id)
    except ClientError as error:
        error_code = error.response.get("Error", {}).get("Code")
        if error_code == "ResourceNotFoundException":
            if _looks_like_arn(secret_id):
                raise ValueError(
                    f"Cannot create a secret from ARN: {secret_id}"
                ) from error
            try:
                client.create_secret(Name=secret_id, SecretString=serialized_payload)
            except Exception as create_error:
                print(traceback.format_exc())
                raise RuntimeError(
                    f"Failed to create runtime secret: {secret_id}"
                ) from create_error
            return secret_id

        print(traceback.format_exc())
        raise RuntimeError(f"Failed to inspect runtime secret: {secret_id}") from error

    try:
        client.put_secret_value(SecretId=secret_id, SecretString=serialized_payload)
    except Exception as error:
        print(traceback.format_exc())
        raise RuntimeError(f"Failed to update runtime secret: {secret_id}") from error

    return secret_id


def _looks_like_arn(secret_id: str) -> bool:
    return secret_id.startswith("arn:")
