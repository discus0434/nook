import json
from argparse import Namespace
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from nook.services.catalog import SERVICE_DEFINITIONS


class FakeSecretsManagerClient:
    def __init__(self, existing: set[str] | None = None) -> None:
        self.existing = existing or set()
        self.created: list[tuple[str, str]] = []
        self.updated: list[tuple[str, str]] = []

    def describe_secret(self, *, SecretId: str) -> dict[str, str]:
        if SecretId not in self.existing:
            raise ClientError(
                {"Error": {"Code": "ResourceNotFoundException", "Message": "missing"}},
                "DescribeSecret",
            )
        return {"ARN": SecretId}

    def create_secret(self, *, Name: str, SecretString: str) -> dict[str, str]:
        self.created.append((Name, SecretString))
        self.existing.add(Name)
        return {"ARN": Name}

    def put_secret_value(self, *, SecretId: str, SecretString: str) -> dict[str, str]:
        self.updated.append((SecretId, SecretString))
        return {"ARN": SecretId}


def test_aws_stack_config_requires_gemini_model() -> None:
    from nook.deploy.aws.runtime_config import AwsStackConfig

    with pytest.raises(
        ValueError, match="Missing required environment variable: GEMINI_MODEL"
    ):
        AwsStackConfig.from_env({})


def test_aws_stack_config_reads_optional_gemini_model() -> None:
    from nook.deploy.aws.runtime_config import AwsStackConfig

    config = AwsStackConfig.from_env({"GEMINI_MODEL": "gemini-2.5-flash"})

    assert config.gemini_model == "gemini-2.5-flash"


def test_build_runtime_environment_includes_required_gemini_model() -> None:
    from nook.deploy.aws.runtime_config import build_runtime_environment

    environment = build_runtime_environment(
        bucket_name="bucket-name",
        runtime_secret_id="my-nook/runtime-secrets",
        gemini_model="gemini-2.5-flash",
    )

    assert environment == {
        "BUCKET_NAME": "bucket-name",
        "GEMINI_MODEL": "gemini-2.5-flash",
        "NOOK_RUNTIME_MODE": "aws",
        "NOOK_STORAGE_BACKEND": "s3",
        "NOOK_AWS_SECRET_ID": "my-nook/runtime-secrets",
    }


def test_requirements_paths_exist_for_all_services() -> None:
    from nook.deploy.aws.runtime_config import (
        COMMON_REQUIREMENTS,
        RUNTIME_SOURCE_DIRECTORIES,
        requirements_path_for,
    )

    assert COMMON_REQUIREMENTS.exists()
    assert tuple(path.as_posix() for path in RUNTIME_SOURCE_DIRECTORIES) == (
        "nook",
        "configs",
    )
    for definition in SERVICE_DEFINITIONS:
        assert requirements_path_for(definition.name).exists(), definition.name


def test_build_secret_payload_collects_only_supported_keys() -> None:
    from nook.deploy.aws.secret_bootstrap import build_secret_payload

    payload = build_secret_payload(
        {
            "GEMINI_API_KEY": "gemini",
            "REDDIT_CLIENT_ID": "reddit-client",
            "UNRELATED_KEY": "ignored",
        }
    )

    assert payload == {
        "GEMINI_API_KEY": "gemini",
        "REDDIT_CLIENT_ID": "reddit-client",
    }


def test_upsert_runtime_secret_creates_when_missing() -> None:
    from nook.deploy.aws.secret_bootstrap import upsert_runtime_secret

    client = FakeSecretsManagerClient()
    secret_id = upsert_runtime_secret(
        env={
            "NOOK_AWS_SECRET_ID": "my-nook/runtime-secrets",
            "GEMINI_API_KEY": "gemini",
        },
        secrets_client=client,
    )

    assert secret_id == "my-nook/runtime-secrets"
    assert client.created == [
        (
            "my-nook/runtime-secrets",
            json.dumps({"GEMINI_API_KEY": "gemini"}, sort_keys=True),
        )
    ]
    assert client.updated == []


def test_upsert_runtime_secret_updates_existing_secret() -> None:
    from nook.deploy.aws.secret_bootstrap import upsert_runtime_secret

    client = FakeSecretsManagerClient(existing={"my-nook/runtime-secrets"})
    secret_id = upsert_runtime_secret(
        env={
            "NOOK_AWS_SECRET_ID": "my-nook/runtime-secrets",
            "GEMINI_API_KEY": "gemini",
            "REDDIT_CLIENT_ID": "reddit-client",
        },
        secrets_client=client,
    )

    assert secret_id == "my-nook/runtime-secrets"
    assert client.created == []
    assert client.updated == [
        (
            "my-nook/runtime-secrets",
            json.dumps(
                {
                    "GEMINI_API_KEY": "gemini",
                    "REDDIT_CLIENT_ID": "reddit-client",
                },
                sort_keys=True,
            ),
        )
    ]


def test_upsert_runtime_secret_rejects_creating_missing_arn_secret() -> None:
    from nook.deploy.aws.secret_bootstrap import upsert_runtime_secret

    with pytest.raises(ValueError, match="Cannot create a secret from ARN"):
        upsert_runtime_secret(
            env={
                "NOOK_AWS_SECRET_ID": (
                    "arn:aws:secretsmanager:ap-northeast-1:123456789012:"
                    "secret:my-nook/runtime-secrets"
                ),
                "GEMINI_API_KEY": "gemini",
            },
            secrets_client=FakeSecretsManagerClient(),
        )


def test_upsert_runtime_secret_is_noop_for_empty_payload() -> None:
    from nook.deploy.aws.secret_bootstrap import upsert_runtime_secret

    client = FakeSecretsManagerClient()
    secret_id = upsert_runtime_secret(
        env={"NOOK_AWS_SECRET_ID": "my-nook/runtime-secrets"},
        secrets_client=client,
    )

    assert secret_id == "my-nook/runtime-secrets"
    assert client.created == []
    assert client.updated == []


def test_build_command_env_merges_dotenv_without_overriding_process_env(
    tmp_path: Path,
) -> None:
    from nook.deploy.aws.cli import build_command_env

    (tmp_path / ".env").write_text(
        (
            "GEMINI_API_KEY=from-dotenv\n"
            "GEMINI_MODEL=gemini-2.5-flash\n"
            "REDDIT_CLIENT_ID=from-dotenv\n"
        ),
        encoding="utf-8",
    )

    env = build_command_env(
        repo_root=tmp_path,
        base_env={"REDDIT_CLIENT_ID": "from-process"},
    )

    assert env["GEMINI_API_KEY"] == "from-dotenv"
    assert env["GEMINI_MODEL"] == "gemini-2.5-flash"
    assert env["REDDIT_CLIENT_ID"] == "from-process"


def test_deploy_command_upserts_secret_with_dotenv_enriched_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from nook.deploy.aws import cli as aws_cli
    from nook.services.runtime import RuntimeSettings

    (tmp_path / ".env").write_text(
        "GEMINI_API_KEY=from-dotenv\nGEMINI_MODEL=gemini-2.5-flash\n",
        encoding="utf-8",
    )

    captured_env: dict[str, str] = {}
    run_calls: list[tuple[list[str], dict[str, str]]] = []

    monkeypatch.setattr(
        aws_cli,
        "build_parser",
        lambda: type(
            "Parser",
            (),
            {"parse_args": staticmethod(lambda: Namespace(command="deploy"))},
        )(),
    )
    monkeypatch.setattr(
        aws_cli.RuntimeSettings,
        "from_env",
        classmethod(
            lambda cls, env: RuntimeSettings(
                runtime_mode="local",
                repo_root=tmp_path,
                local_host="0.0.0.0",
                local_port=8080,
            )
        ),
    )
    monkeypatch.setattr(
        aws_cli,
        "upsert_runtime_secret",
        lambda *, env: captured_env.update(env) or "synced-secret",
    )
    monkeypatch.setattr(
        aws_cli.subprocess,
        "run",
        lambda command, cwd, check, env: run_calls.append((command, env)),
    )

    aws_cli.main()

    assert captured_env["GEMINI_API_KEY"] == "from-dotenv"
    assert captured_env["GEMINI_MODEL"] == "gemini-2.5-flash"
    assert run_calls
    assert run_calls[0][0] == ["cdk", "deploy"]
    assert run_calls[0][1]["GEMINI_API_KEY"] == "from-dotenv"
    assert run_calls[0][1]["GEMINI_MODEL"] == "gemini-2.5-flash"
    assert run_calls[0][1]["NOOK_AWS_SECRET_ID"] == "synced-secret"
