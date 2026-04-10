from pathlib import Path

import pytest

from nook.deploy.local import cli
from nook.deploy.local.manifests import (
    render_launchd_plist,
    render_systemd_service,
    render_systemd_timer,
)
from nook.deploy.local.paths import detect_platform
from nook.services.catalog import get_service_definition


def test_render_systemd_service_for_viewer_contains_expected_execstart(
    tmp_path: Path,
) -> None:
    definition = get_service_definition("viewer")

    rendered = render_systemd_service(
        definition=definition,
        repo_root=tmp_path,
        uv_executable="/opt/homebrew/bin/uv",
    )

    assert "Description=my-nook viewer service" in rendered
    assert "WorkingDirectory=" + str(tmp_path) in rendered
    assert "Environment=NOOK_UV_EXECUTABLE=/opt/homebrew/bin/uv" in rendered
    assert (
        "ExecStart=/bin/bash -lc '/opt/homebrew/bin/uv run python -m "
        "nook.deploy.local.cli run-viewer'"
    ) in rendered


def test_render_systemd_service_for_collector_sets_timeout(
    tmp_path: Path,
) -> None:
    definition = get_service_definition("tech_news")

    rendered = render_systemd_service(
        definition=definition,
        repo_root=tmp_path,
        uv_executable="/opt/homebrew/bin/uv",
    )

    assert "Type=oneshot" in rendered
    assert "TimeoutStartSec=15min" in rendered


def test_render_systemd_timer_uses_catalog_schedule() -> None:
    definition = get_service_definition("tech_feed")

    rendered = render_systemd_timer(definition)

    assert "Unit=my-nook-tech_feed.service" in rendered
    assert "OnCalendar=*-*-* 00:18:00" in rendered


def test_render_launchd_plist_contains_expected_program_arguments(
    tmp_path: Path,
) -> None:
    definition = get_service_definition("product_hunt")

    rendered = render_launchd_plist(
        definition=definition,
        repo_root=tmp_path,
        uv_executable="/usr/local/bin/uv",
    )

    assert rendered["Label"] == "com.my-nook.product_hunt"
    assert rendered["WorkingDirectory"] == str(tmp_path)
    assert rendered["EnvironmentVariables"] == {
        "PYTHONUNBUFFERED": "1",
        "NOOK_UV_EXECUTABLE": "/usr/local/bin/uv",
    }
    assert rendered["ProgramArguments"] == [
        "/bin/bash",
        "-lc",
        "/usr/local/bin/uv run python -m nook.deploy.local.cli run-job product_hunt",
    ]
    assert rendered["StartCalendarInterval"] == {"Hour": 0, "Minute": 30}


def test_detect_platform_rejects_unknown_os() -> None:
    with pytest.raises(ValueError, match="Unsupported platform"):
        detect_platform(system_name="Windows")


def test_run_job_invokes_collector_directly(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        cli, "run_collector", lambda service_name: calls.append(service_name)
    )

    cli.run_job("tech_feed")

    assert calls == ["tech_feed"]


def test_run_job_rejects_non_collector_service() -> None:
    with pytest.raises(ValueError, match="is not a collector service"):
        cli.run_job("viewer")
