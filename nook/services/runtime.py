import json
import os
import shutil
import subprocess
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol

import boto3

from nook.services.catalog import SERVICE_DEFINITIONS, ServiceDefinition


class JobInvoker(Protocol):
    def trigger(self, service_name: str) -> None: ...


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    runtime_mode: str
    repo_root: Path
    local_host: str
    local_port: int

    @classmethod
    def from_env(cls, env: Mapping[str, str | None]) -> "RuntimeSettings":
        runtime_mode = env.get("NOOK_RUNTIME_MODE") or _default_runtime_mode(env)
        repo_root = Path(env.get("NOOK_REPO_ROOT") or _default_repo_root())
        local_host = env.get("NOOK_LOCAL_HOST") or "0.0.0.0"
        local_port = int(env.get("NOOK_LOCAL_PORT") or "8080")
        return cls(
            runtime_mode=runtime_mode,
            repo_root=repo_root,
            local_host=local_host,
            local_port=local_port,
        )


@dataclass(slots=True)
class AwsLambdaJobInvoker:
    function_arns: Mapping[str, str | None]
    _client: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._client = boto3.client("lambda")

    def trigger(self, service_name: str) -> None:
        function_arn = self.function_arns.get(service_name)
        if not function_arn:
            raise ValueError(f"Missing Lambda function ARN for {service_name}")

        response = self._client.invoke(
            FunctionName=function_arn,
            InvocationType="Event",
            Payload=json.dumps({"source": "aws.events"}),
        )
        if response.get("StatusCode") != 202:
            raise RuntimeError(
                f"Failed to invoke Lambda for {service_name}: "
                f"status={response.get('StatusCode')} "
                f"function_error={response.get('FunctionError')}"
            )


@dataclass(frozen=True, slots=True)
class LocalSubprocessJobInvoker:
    repo_root: Path
    uv_executable: str

    def trigger(self, service_name: str) -> None:
        command = self.command_for(service_name)
        try:
            subprocess.Popen(
                ["/bin/bash", "-lc", command],
                cwd=self.repo_root,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as error:
            print(traceback.format_exc())
            raise RuntimeError(f"Failed to trigger local job {service_name}") from error

    def command_for(self, service_name: str) -> str:
        return (
            f"{self.uv_executable} run python -m "
            f"nook.deploy.local.cli run-job {service_name}"
        )


def build_job_invoker(env: Mapping[str, str | None]) -> JobInvoker:
    settings = RuntimeSettings.from_env(env)
    if settings.runtime_mode == "aws":
        function_arns = {
            definition.name: env.get(f"{definition.name.upper()}_FUNCTION_ARN")
            for definition in SERVICE_DEFINITIONS
            if definition.kind == "collector"
        }
        return AwsLambdaJobInvoker(function_arns=function_arns)

    return LocalSubprocessJobInvoker(
        repo_root=settings.repo_root,
        uv_executable=_resolve_local_uv_executable(
            env=env,
            repo_root=settings.repo_root,
        ),
    )


def get_viewer_services() -> list[ServiceDefinition]:
    return [
        definition
        for definition in SERVICE_DEFINITIONS
        if definition.kind == "collector"
    ]


def _default_runtime_mode(env: Mapping[str, str | None]) -> str:
    if env.get("AWS_EXECUTION_ENV"):
        return "aws"
    return "local"


def _default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_local_uv_executable(
    *,
    env: Mapping[str, str | None],
    repo_root: Path,
) -> str:
    configured_uv = env.get("NOOK_UV_EXECUTABLE")
    if configured_uv:
        return configured_uv

    repo_uv = repo_root / ".venv" / "bin" / "uv"
    if repo_uv.exists():
        return str(repo_uv)

    uv_executable = shutil.which("uv")
    if uv_executable:
        return uv_executable

    raise ValueError("uv executable was not found")
