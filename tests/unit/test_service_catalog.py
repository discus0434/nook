import pytest

from nook.services.catalog import SERVICE_DEFINITIONS, get_service_definition


def test_service_catalog_contains_all_collectors_and_viewer() -> None:
    definitions = {definition.name: definition for definition in SERVICE_DEFINITIONS}

    assert list(definitions) == [
        "hacker_news",
        "paper_summarizer",
        "reddit_explorer",
        "tech_feed",
        "github_trending",
        "product_hunt",
        "viewer",
        "google_alerts",
        "tech_news",
    ]
    assert definitions["viewer"].kind == "web"

    collector_names = [
        definition.name
        for definition in SERVICE_DEFINITIONS
        if definition.kind == "collector"
    ]
    assert collector_names == [
        "hacker_news",
        "paper_summarizer",
        "reddit_explorer",
        "tech_feed",
        "github_trending",
        "product_hunt",
        "google_alerts",
        "tech_news",
    ]


def test_collector_schedules_preserve_existing_staggering() -> None:
    assert get_service_definition("hacker_news").schedule == (0, 0)
    assert get_service_definition("paper_summarizer").schedule == (0, 6)
    assert get_service_definition("reddit_explorer").schedule == (0, 12)
    assert get_service_definition("tech_feed").schedule == (0, 18)
    assert get_service_definition("github_trending").schedule == (0, 24)
    assert get_service_definition("product_hunt").schedule == (0, 30)
    assert get_service_definition("google_alerts").schedule == (0, 42)
    assert get_service_definition("tech_news").schedule == (0, 48)
    assert get_service_definition("viewer").schedule is None


def test_get_service_definition_rejects_unknown_name() -> None:
    with pytest.raises(KeyError, match="unknown service"):
        get_service_definition("unknown")
