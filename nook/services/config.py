from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Mapping


def config_root(env: Mapping[str, str | None] | None = None) -> Path:
    resolved_env = env or os.environ
    repo_root = resolved_env.get("NOOK_REPO_ROOT")
    if repo_root:
        return Path(repo_root).resolve() / "configs"
    return Path(__file__).resolve().parents[2] / "configs"


def service_config_path(
    service_name: str,
    filename: str,
    *,
    env: Mapping[str, str | None] | None = None,
) -> Path:
    return config_root(env) / service_name / filename


def load_service_toml(
    service_name: str,
    filename: str,
    *,
    env: Mapping[str, str | None] | None = None,
) -> dict[str, Any]:
    path = service_config_path(service_name, filename, env=env)
    with path.open("rb") as file:
        return tomllib.load(file)
