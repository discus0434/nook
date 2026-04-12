import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest

from nook.services.config import load_service_toml, service_config_path
from nook.services.github_trending.service import Config as GithubTrendingConfig
from nook.services.google_alerts.service import Config as GoogleAlertsConfig
from nook.services.reddit_explorer.service import Config as RedditExplorerConfig
from nook.services.tech_feed.service import Config as TechFeedConfig
from nook.services.tech_news.service import Config as TechNewsConfig


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


def load_raw_service_toml(service_name: str, filename: str) -> dict:
    path = service_config_path(service_name, filename)
    with path.open("rb") as file:
        return tomllib.load(file)


def expected_tech_feed_feeds(data: dict) -> dict[str, str]:
    return {feed["name"]: feed["url"] for feed in data["feeds"]}


def expected_github_trending_languages(data: dict) -> list[str]:
    return [language["name"] for language in data["languages"]]


def expected_reddit_subreddits(data: dict) -> list[str]:
    return [subreddit["name"] for subreddit in data["subreddits"]]


def expected_tech_news_feeds(data: dict) -> list[dict[str, object]]:
    return [{**feed, "keywords": feed.get("keywords")} for feed in data["feeds"]]


CONFIG_LOADER_CASES: list[
    tuple[str, str, Callable[[], object], Callable[[dict], object]]
] = [
    (
        "tech_feed",
        "feed.toml",
        TechFeedConfig.load_feeds,
        expected_tech_feed_feeds,
    ),
    (
        "google_alerts",
        "google_alerts.toml",
        GoogleAlertsConfig.load_alerts,
        lambda data: data["alerts"],
    ),
    (
        "github_trending",
        "languages.toml",
        GithubTrendingConfig.load_languages,
        expected_github_trending_languages,
    ),
    (
        "reddit_explorer",
        "subreddits.toml",
        RedditExplorerConfig.load_subreddits,
        expected_reddit_subreddits,
    ),
    (
        "tech_news",
        "feed.toml",
        lambda: [feed.model_dump() for feed in TechNewsConfig.load_feeds()],
        expected_tech_news_feeds,
    ),
]


@pytest.mark.parametrize(
    ("service_name", "filename", "loader", "expected_builder"),
    CONFIG_LOADER_CASES,
)
def test_service_specific_config_loaders_match_toml(
    service_name: str,
    filename: str,
    loader: Callable[[], object],
    expected_builder: Callable[[dict], object],
) -> None:
    raw_data = load_raw_service_toml(service_name, filename)

    assert loader() == expected_builder(raw_data)


def test_google_alerts_load_alerts_propagates_missing_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("NOOK_REPO_ROOT", str(tmp_path))

    with pytest.raises(FileNotFoundError):
        GoogleAlertsConfig.load_alerts()


def test_tech_news_load_feeds_propagates_missing_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("NOOK_REPO_ROOT", str(tmp_path))

    with pytest.raises(FileNotFoundError):
        TechNewsConfig.load_feeds()
