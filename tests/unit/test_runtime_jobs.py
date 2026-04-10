from pathlib import Path

import pytest

from nook.services.runtime import (
    AwsLambdaJobInvoker,
    LocalSubprocessJobInvoker,
    build_job_invoker,
)


def test_build_job_invoker_prefers_repo_venv_uv_when_env_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    uv_path = tmp_path / ".venv" / "bin" / "uv"
    uv_path.parent.mkdir(parents=True)
    uv_path.write_text("", encoding="utf-8")
    monkeypatch.setattr("nook.services.runtime.shutil.which", lambda name: None)

    invoker = build_job_invoker(
        {
            "NOOK_RUNTIME_MODE": "local",
            "NOOK_REPO_ROOT": str(tmp_path),
        }
    )

    assert isinstance(invoker, LocalSubprocessJobInvoker)
    assert invoker.uv_executable == str(uv_path)


def test_build_job_invoker_prefers_configured_uv_over_repo_or_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    uv_path = tmp_path / ".venv" / "bin" / "uv"
    uv_path.parent.mkdir(parents=True)
    uv_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        "nook.services.runtime.shutil.which", lambda name: "/usr/bin/uv"
    )

    invoker = build_job_invoker(
        {
            "NOOK_RUNTIME_MODE": "local",
            "NOOK_REPO_ROOT": str(tmp_path),
            "NOOK_UV_EXECUTABLE": "/opt/custom/uv",
        }
    )

    assert isinstance(invoker, LocalSubprocessJobInvoker)
    assert invoker.uv_executable == "/opt/custom/uv"


def test_build_job_invoker_falls_back_to_path_uv_when_repo_venv_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "nook.services.runtime.shutil.which", lambda name: "/usr/bin/uv"
    )

    invoker = build_job_invoker(
        {
            "NOOK_RUNTIME_MODE": "local",
            "NOOK_REPO_ROOT": str(tmp_path),
        }
    )

    assert isinstance(invoker, LocalSubprocessJobInvoker)
    assert invoker.uv_executable == "/usr/bin/uv"


def test_build_job_invoker_raises_when_uv_is_missing_everywhere(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("nook.services.runtime.shutil.which", lambda name: None)

    with pytest.raises(ValueError, match="uv executable was not found"):
        build_job_invoker(
            {
                "NOOK_RUNTIME_MODE": "local",
                "NOOK_REPO_ROOT": str(tmp_path),
            }
        )


def test_aws_lambda_job_invoker_initializes_boto_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nook.services.runtime as runtime

    fake_client = object()
    monkeypatch.setattr(runtime.boto3, "client", lambda service_name: fake_client)

    invoker = AwsLambdaJobInvoker(function_arns={"tech_feed": "arn:aws:lambda:::fn"})

    assert invoker._client is fake_client
