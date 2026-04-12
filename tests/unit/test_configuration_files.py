import tomllib
from pathlib import Path

import pytest

CONFIG_CASES = [
    (
        Path("configs/tech_feed/feed.toml"),
        "feeds",
        {"key", "name", "url"},
    ),
    (
        Path("configs/google_alerts/google_alerts.toml"),
        "alerts",
        {"name", "url"},
    ),
    (
        Path("configs/github_trending/languages.toml"),
        "languages",
        {"name"},
    ),
    (
        Path("configs/reddit_explorer/subreddits.toml"),
        "subreddits",
        {"name"},
    ),
    (
        Path("configs/tech_news/feed.toml"),
        "feeds",
        {"name", "url", "feed_name_display"},
    ),
]


def load_toml(path: Path) -> dict:
    with path.open("rb") as file:
        return tomllib.load(file)


@pytest.mark.parametrize(("path", "key", "required_fields"), CONFIG_CASES)
def test_configuration_lists_have_required_fields(
    path: Path,
    key: str,
    required_fields: set[str],
) -> None:
    data = load_toml(path)

    assert key in data
    assert data[key]

    for item in data[key]:
        assert required_fields.issubset(item)
        for field in required_fields:
            assert item[field]


def test_tech_news_keywords_are_non_empty_strings() -> None:
    data = load_toml(Path("configs/tech_news/feed.toml"))

    keyword_sets = [
        feed.get("keywords") for feed in data["feeds"] if "keywords" in feed
    ]

    assert keyword_sets
    for keywords in keyword_sets:
        assert keywords
        assert all(isinstance(keyword, str) and keyword for keyword in keywords)
