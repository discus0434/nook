import shlex
from pathlib import Path

from nook.deploy.local.paths import launchd_label, service_unit_name
from nook.services.catalog import ServiceDefinition


def render_systemd_service(
    definition: ServiceDefinition,
    repo_root: Path,
    uv_executable: str,
) -> str:
    command = _local_command(definition, uv_executable)
    restart = "always" if definition.kind == "web" else "no"
    service_type = "simple" if definition.kind == "web" else "oneshot"
    lines = [
        "[Unit]",
        f"Description=my-nook {definition.name} service",
        "",
        "[Service]",
        f"Type={service_type}",
        f"WorkingDirectory={repo_root}",
        "Environment=PYTHONUNBUFFERED=1",
        f"Environment=NOOK_UV_EXECUTABLE={uv_executable}",
        f"ExecStart=/bin/bash -lc {shlex.quote(command)}",
        f"Restart={restart}",
    ]
    if definition.kind != "web":
        lines.append("TimeoutStartSec=15min")

    lines.extend(
        [
            "",
            "[Install]",
            "WantedBy=default.target",
            "",
        ]
    )
    return "\n".join(lines)


def render_systemd_timer(definition: ServiceDefinition) -> str:
    if definition.schedule is None:
        raise ValueError(f"Service {definition.name} does not define a schedule")
    hour, minute = definition.schedule
    return "\n".join(
        [
            "[Unit]",
            f"Description=Schedule for my-nook {definition.name}",
            "",
            "[Timer]",
            f"OnCalendar=*-*-* {hour:02d}:{minute:02d}:00",
            "Persistent=true",
            f"Unit={service_unit_name(definition.name)}",
            "",
            "[Install]",
            "WantedBy=timers.target",
            "",
        ]
    )


def render_launchd_plist(
    definition: ServiceDefinition,
    repo_root: Path,
    uv_executable: str,
) -> dict[str, object]:
    command = _local_command(definition, uv_executable)
    plist: dict[str, object] = {
        "Label": launchd_label(definition.name),
        "WorkingDirectory": str(repo_root),
        "ProgramArguments": ["/bin/bash", "-lc", command],
        "EnvironmentVariables": {
            "PYTHONUNBUFFERED": "1",
            "NOOK_UV_EXECUTABLE": uv_executable,
        },
        "StandardOutPath": str(repo_root / ".nook" / "logs" / f"{definition.name}.log"),
        "StandardErrorPath": str(
            repo_root / ".nook" / "logs" / f"{definition.name}.err.log"
        ),
    }

    if definition.kind == "web":
        plist["RunAtLoad"] = True
        plist["KeepAlive"] = True
    else:
        if definition.schedule is None:
            raise ValueError(f"Service {definition.name} does not define a schedule")
        hour, minute = definition.schedule
        plist["StartCalendarInterval"] = {"Hour": hour, "Minute": minute}

    return plist


def _local_command(definition: ServiceDefinition, uv_executable: str) -> str:
    base = f"{shlex.quote(uv_executable)} run python -m nook.deploy.local.cli"
    if definition.kind == "web":
        return f"{base} run-viewer"
    return f"{base} run-job {definition.name}"
