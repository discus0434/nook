import platform
from pathlib import Path
from typing import Literal

SupportedPlatform = Literal["ubuntu", "mac"]


def detect_platform(system_name: str | None = None) -> SupportedPlatform:
    system = (system_name or platform.system()).lower()
    if system == "linux":
        return "ubuntu"
    if system == "darwin":
        return "mac"
    raise ValueError(f"Unsupported platform: {system_name or platform.system()}")


def systemd_user_dir(home_dir: Path) -> Path:
    return home_dir / ".config" / "systemd" / "user"


def launchd_user_dir(home_dir: Path) -> Path:
    return home_dir / "Library" / "LaunchAgents"


def service_unit_name(service_name: str) -> str:
    return f"my-nook-{service_name}.service"


def timer_unit_name(service_name: str) -> str:
    return f"my-nook-{service_name}.timer"


def launchd_label(service_name: str) -> str:
    return f"com.my-nook.{service_name}"
