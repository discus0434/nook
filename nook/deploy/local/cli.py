import argparse
import os
import plistlib
import shutil
import subprocess
import traceback
from pathlib import Path

from dotenv import load_dotenv

from nook.deploy.local.manifests import (
    render_launchd_plist,
    render_systemd_service,
    render_systemd_timer,
)
from nook.deploy.local.paths import (
    detect_platform,
    launchd_label,
    launchd_user_dir,
    service_unit_name,
    systemd_user_dir,
    timer_unit_name,
)
from nook.services.catalog import SERVICE_DEFINITIONS, get_service_definition
from nook.services.registry import run_collector
from nook.services.runtime import RuntimeSettings
from nook.services.viewer.app import build_app_from_env


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m nook.deploy.local.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    register = subparsers.add_parser("register")
    register.add_argument(
        "--platform", choices=["auto", "ubuntu", "mac"], default="auto"
    )
    register.add_argument("--repo-root")

    unregister = subparsers.add_parser("unregister")
    unregister.add_argument(
        "--platform",
        choices=["auto", "ubuntu", "mac"],
        default="auto",
    )
    unregister.add_argument("--repo-root")

    subparsers.add_parser("run-viewer")

    run_job = subparsers.add_parser("run-job")
    run_job.add_argument("service_name")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "register":
            register_services(
                platform_name=_normalize_platform(args.platform),
                repo_root=_resolve_repo_root(args.repo_root),
            )
            return 0

        if args.command == "unregister":
            unregister_services(
                platform_name=_normalize_platform(args.platform),
                repo_root=_resolve_repo_root(args.repo_root),
            )
            return 0

        load_local_env()
        if args.command == "run-viewer":
            run_viewer()
            return 0

        if args.command == "run-job":
            run_job(args.service_name)
            return 0
    except Exception:
        print(traceback.format_exc())
        raise

    parser.error(f"Unsupported command: {args.command}")
    return 2


def register_services(platform_name: str, repo_root: Path) -> None:
    uv_executable = shutil.which("uv")
    if not uv_executable:
        raise ValueError("uv executable was not found")

    logs_dir = repo_root / ".nook" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    if platform_name == "ubuntu":
        target_dir = systemd_user_dir(Path.home())
        target_dir.mkdir(parents=True, exist_ok=True)
        for definition in SERVICE_DEFINITIONS:
            service_path = target_dir / service_unit_name(definition.name)
            service_path.write_text(
                render_systemd_service(definition, repo_root, uv_executable),
                encoding="utf-8",
            )
            if definition.kind == "collector":
                timer_path = target_dir / timer_unit_name(definition.name)
                timer_path.write_text(
                    render_systemd_timer(definition),
                    encoding="utf-8",
                )

        _run(["systemctl", "--user", "daemon-reload"])
        _run(
            ["systemctl", "--user", "enable", "--now", service_unit_name("viewer")],
        )
        _run(["systemctl", "--user", "restart", service_unit_name("viewer")])
        for definition in SERVICE_DEFINITIONS:
            if definition.kind != "collector":
                continue
            timer_name = timer_unit_name(definition.name)
            _run(["systemctl", "--user", "enable", "--now", timer_name])
            _run(["systemctl", "--user", "restart", timer_name])
        return

    if platform_name == "mac":
        target_dir = launchd_user_dir(Path.home())
        target_dir.mkdir(parents=True, exist_ok=True)
        domain = f"gui/{os.getuid()}"
        for definition in SERVICE_DEFINITIONS:
            plist_path = target_dir / f"{launchd_label(definition.name)}.plist"
            plist_path.write_bytes(
                plistlib.dumps(
                    render_launchd_plist(definition, repo_root, uv_executable),
                ),
            )
            _run(
                ["launchctl", "bootout", domain, str(plist_path)],
                check=False,
            )
            _run(["launchctl", "bootstrap", domain, str(plist_path)])
        return

    raise ValueError(f"Unsupported platform: {platform_name}")


def unregister_services(platform_name: str, repo_root: Path) -> None:
    _ = repo_root
    if platform_name == "ubuntu":
        target_dir = systemd_user_dir(Path.home())
        for definition in SERVICE_DEFINITIONS:
            if definition.kind == "collector":
                _run(
                    [
                        "systemctl",
                        "--user",
                        "disable",
                        "--now",
                        timer_unit_name(definition.name),
                    ],
                    check=False,
                )
                (target_dir / timer_unit_name(definition.name)).unlink(missing_ok=True)
            _run(
                [
                    "systemctl",
                    "--user",
                    "disable",
                    "--now",
                    service_unit_name(definition.name),
                ],
                check=False,
            )
            (target_dir / service_unit_name(definition.name)).unlink(missing_ok=True)
        _run(["systemctl", "--user", "daemon-reload"], check=False)
        return

    if platform_name == "mac":
        target_dir = launchd_user_dir(Path.home())
        domain = f"gui/{os.getuid()}"
        for definition in SERVICE_DEFINITIONS:
            plist_path = target_dir / f"{launchd_label(definition.name)}.plist"
            _run(["launchctl", "bootout", domain, str(plist_path)], check=False)
            plist_path.unlink(missing_ok=True)
        return

    raise ValueError(f"Unsupported platform: {platform_name}")


def run_viewer() -> None:
    import uvicorn

    settings = RuntimeSettings.from_env(os.environ)
    uvicorn.run(
        build_app_from_env(),
        host=settings.local_host,
        port=settings.local_port,
    )


def run_job(service_name: str) -> None:
    definition = get_service_definition(service_name)
    if definition.kind != "collector":
        raise ValueError(f"{service_name} is not a collector service")

    run_collector(service_name)


def load_local_env() -> None:
    settings = RuntimeSettings.from_env(os.environ)
    load_dotenv(settings.repo_root / ".env")
    os.environ.setdefault("NOOK_RUNTIME_MODE", "local")
    os.environ.setdefault("NOOK_STORAGE_BACKEND", "filesystem")
    os.environ.setdefault("NOOK_REPO_ROOT", str(settings.repo_root))


def _normalize_platform(platform_name: str) -> str:
    if platform_name == "auto":
        return detect_platform()
    return platform_name


def _resolve_repo_root(repo_root: str | None) -> Path:
    if repo_root:
        return Path(repo_root).resolve()
    return RuntimeSettings.from_env(os.environ).repo_root


def _run(command: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=check, text=True, capture_output=True)


if __name__ == "__main__":
    raise SystemExit(main())
