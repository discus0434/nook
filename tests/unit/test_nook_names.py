from nook.nook_stack import NookNames


def test_nook_names_are_unique() -> None:
    values = list(NookNames().__dict__.values())

    assert len(values) == len(set(values))


def test_nook_names_match_expected_collectors() -> None:
    names = NookNames()

    assert names.hacker_news == "hacker_news"
    assert names.paper_summarizer == "paper_summarizer"
    assert names.reddit_explorer == "reddit_explorer"
    assert names.tech_feed == "tech_feed"
    assert names.github_trending == "github_trending"
    assert names.product_hunt == "product_hunt"
    assert names.viewer == "viewer"
    assert names.google_alerts == "google_alerts"
    assert names.tech_news == "tech_news"
