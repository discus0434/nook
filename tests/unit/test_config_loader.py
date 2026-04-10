import tomllib
from pathlib import Path

import pytest

from nook.services.config import load_service_toml, service_config_path
from nook.services.google_alerts.service import Config as GoogleAlertsConfig


def test_service_config_path_defaults_to_repo_root() -> None:
    path = service_config_path("tech_feed", "feed.toml")

    assert path == Path(__file__).resolve().parents[2] / "configs/tech_feed/feed.toml"


def test_service_config_path_respects_repo_root_override(tmp_path: Path) -> None:
    path = service_config_path(
        "reddit_explorer",
        "subreddits.toml",
        env={"NOOK_REPO_ROOT": str(tmp_path)},
    )

    assert path == tmp_path / "configs/reddit_explorer/subreddits.toml"


def test_load_service_toml_raises_for_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_service_toml(
            "missing-service",
            "missing.toml",
            env={"NOOK_REPO_ROOT": str(tmp_path)},
        )


def test_load_service_toml_raises_for_invalid_toml(tmp_path: Path) -> None:
    config_dir = tmp_path / "configs" / "tech_feed"
    config_dir.mkdir(parents=True)
    (config_dir / "feed.toml").write_text(
        "[[feeds]\nname = 'broken'\n", encoding="utf-8"
    )

    with pytest.raises(tomllib.TOMLDecodeError):
        load_service_toml(
            "tech_feed",
            "feed.toml",
            env={"NOOK_REPO_ROOT": str(tmp_path)},
        )


def test_google_alerts_load_alerts_propagates_missing_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("NOOK_REPO_ROOT", str(tmp_path))

    with pytest.raises(FileNotFoundError):
        GoogleAlertsConfig.load_alerts()
