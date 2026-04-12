from datetime import date, datetime, timezone

import pytest
import requests
from fastapi import HTTPException


class FakeStorage:
    def __init__(self) -> None:
        self.markdowns = {
            (
                "tech_feed",
                date(2026, 4, 8),
            ): "# First Article\n\nAlpha summary.\n\n---\n\n# Second Article\n\nBeta summary."
        }
        self.states: dict[tuple[str, str], str] = {}

    def read_markdown_record(self, service_name: str, day: date):
        content = self.read_markdown(service_name, day)
        if content is None:
            return None

        from nook.services.storage import MarkdownRecord

        return MarkdownRecord(
            content=content,
            updated_at=datetime(2026, 4, 8, 0, 1, tzinfo=timezone.utc),
        )

    def read_markdown(self, service_name: str, day: date) -> str | None:
        return self.markdowns.get((service_name, day))

    def read_state(self, service_name: str, key: str) -> str | None:
        return self.states.get((service_name, key))

    def write_state(self, service_name: str, key: str, content: str) -> None:
        self.states[(service_name, key)] = content


class FakeJobInvoker:
    def __init__(self) -> None:
        self.triggered: list[str] = []

    def trigger(self, service_name: str) -> None:
        self.triggered.append(service_name)


class FailingJobInvoker:
    def trigger(self, service_name: str) -> None:
        _ = service_name
        raise RuntimeError("boom")


def test_load_viewer_page_builds_contents_and_existence_map() -> None:
    from nook.services.viewer.content import load_viewer_page

    page = load_viewer_page(
        storage_backend=FakeStorage(),
        target_day=date(2026, 4, 8),
        weather_data={"temp": "18", "weather_code": "100", "weather_icon": "☀️"},
    )

    assert page.date == "2026-04-08"
    assert (
        page.contents["tech_feed"]
        == "# First Article\n\nAlpha summary.\n\n---\n\n# Second Article\n\nBeta summary."
    )
    assert len(page.articles["tech_feed"]) == 2
    assert page.articles["tech_feed"][0].article_id.startswith("article-tech_feed-")
    assert page.articles["tech_feed"][0].title == "First Article"
    assert page.articles["tech_feed"][0].html
    assert page.articles["tech_feed"][0].headings
    assert page.articles["tech_feed"][1].article_id.startswith("article-tech_feed-")
    assert (
        page.articles["tech_feed"][1].article_id
        != page.articles["tech_feed"][0].article_id
    )
    assert page.articles["tech_feed"][1].title == "Second Article"
    assert page.markdown_exists["tech_feed"] is True
    assert page.markdown_updated_at["tech_feed"] == "2026-04-08T00:01:00+00:00"
    assert page.markdown_exists["tech_news"] is False
    assert "tech_feed" in page.app_names
    assert page.app_names == [
        "tech_news",
        "tech_feed",
        "hacker_news",
        "product_hunt",
        "github_trending",
        "paper_summarizer",
        "google_alerts",
        "reddit_explorer",
    ]


def test_build_initial_render_uses_first_tab_even_when_markdown_is_missing() -> None:
    from nook.services.viewer.content import build_initial_render, load_viewer_page

    page = load_viewer_page(
        storage_backend=FakeStorage(),
        target_day=date(2026, 4, 8),
        weather_data={"temp": "18", "weather_code": "100", "weather_icon": "☀️"},
    )

    initial_render = build_initial_render(page)

    assert initial_render.current_app == "tech_news"
    assert initial_render.tabs[0].is_active is True
    assert initial_render.tabs[0].label == "News"
    assert initial_render.tabs[1].is_active is False
    assert initial_render.article_title == "News"
    assert initial_render.article_meta == "2026-04-08"
    assert initial_render.missing_message == "Content for 2026-04-08 not found."
    assert initial_render.articles == []
    assert initial_render.headings == []


def test_build_initial_render_returns_missing_state_when_markdown_is_unavailable() -> (
    None
):
    from nook.services.viewer.content import build_initial_render, load_viewer_page

    page = load_viewer_page(
        storage_backend=FakeStorage(),
        target_day=date(2026, 4, 9),
        weather_data={"temp": "18", "weather_code": "100", "weather_icon": "☀️"},
    )

    initial_render = build_initial_render(page)

    assert initial_render.current_app == "tech_news"
    assert initial_render.tabs[0].is_active is True
    assert initial_render.article_title == "News"
    assert initial_render.article_meta == "2026-04-09"
    assert initial_render.missing_message == "Content for 2026-04-09 not found."
    assert initial_render.articles == []
    assert initial_render.headings == []


def test_viewer_service_names_uses_priority_order_and_appends_unspecified_services() -> (
    None
):
    from nook.services.viewer.content import viewer_service_names

    assert viewer_service_names() == [
        "tech_news",
        "tech_feed",
        "hacker_news",
        "product_hunt",
        "github_trending",
        "paper_summarizer",
        "google_alerts",
        "reddit_explorer",
    ]


def test_split_markdown_into_articles_treats_single_section_as_one_article() -> None:
    from nook.services.viewer.content import split_markdown_into_articles

    articles = split_markdown_into_articles(
        app_name="tech_feed",
        markdown_text="# Only Article\n\nStandalone summary.",
    )

    assert len(articles) == 1
    assert articles[0].article_id.startswith("article-tech_feed-")
    assert [article.title for article in articles] == ["Only Article"]
    assert [article.markdown for article in articles] == [
        "# Only Article\n\nStandalone summary."
    ]


def test_split_markdown_into_articles_keeps_stable_ids_when_article_is_inserted() -> (
    None
):
    from nook.services.viewer.content import split_markdown_into_articles

    original_articles = split_markdown_into_articles(
        app_name="tech_feed",
        markdown_text="# First Article\n\nAlpha summary.\n\n---\n\n# Second Article\n\nBeta summary.",
    )
    updated_articles = split_markdown_into_articles(
        app_name="tech_feed",
        markdown_text="# New Article\n\nGamma summary.\n\n---\n\n# First Article\n\nAlpha summary.\n\n---\n\n# Second Article\n\nBeta summary.",
    )

    original_ids = {article.title: article.article_id for article in original_articles}
    updated_ids = {article.title: article.article_id for article in updated_articles}

    assert updated_ids["First Article"] == original_ids["First Article"]
    assert updated_ids["Second Article"] == original_ids["Second Article"]
    assert updated_ids["New Article"] not in original_ids.values()


def test_split_markdown_into_articles_assigns_distinct_ids_to_duplicate_content() -> (
    None
):
    from nook.services.viewer.content import split_markdown_into_articles

    articles = split_markdown_into_articles(
        app_name="tech_feed",
        markdown_text="# Duplicate\n\nAlpha summary.\n\n---\n\n# Other\n\nBeta summary.\n\n---\n\n# Duplicate\n\nAlpha summary.",
    )
    duplicate_ids = [
        article.article_id for article in articles if article.title == "Duplicate"
    ]

    assert len(duplicate_ids) == 2
    assert len(set(duplicate_ids)) == 2


def test_load_viewer_page_reuses_duplicate_article_ids_from_persisted_state() -> None:
    from nook.services.viewer.content import load_viewer_page

    storage = FakeStorage()
    storage.markdowns[("tech_feed", date(2026, 4, 8))] = (
        "# Duplicate\n\nAlpha summary.\n\n---\n\n# Other\n\nBeta summary.\n\n---\n\n# Duplicate\n\nAlpha summary."
    )

    original_page = load_viewer_page(
        storage_backend=storage,
        target_day=date(2026, 4, 8),
        weather_data={"temp": "18", "weather_code": "100", "weather_icon": "☀️"},
    )
    original_articles = original_page.articles["tech_feed"]

    storage.markdowns[("tech_feed", date(2026, 4, 8))] = (
        "# Duplicate\n\nAlpha summary.\n\n---\n\n# Duplicate\n\nAlpha summary.\n\n---\n\n# Other\n\nBeta summary.\n\n---\n\n# Duplicate\n\nAlpha summary."
    )

    updated_page = load_viewer_page(
        storage_backend=storage,
        target_day=date(2026, 4, 8),
        weather_data={"temp": "18", "weather_code": "100", "weather_icon": "☀️"},
    )
    updated_articles = updated_page.articles["tech_feed"]

    assert len({article.article_id for article in original_articles}) == 3
    assert len({article.article_id for article in updated_articles}) == 4
    assert updated_articles[1].article_id == original_articles[0].article_id
    assert updated_articles[2].article_id == original_articles[1].article_id
    assert updated_articles[3].article_id == original_articles[2].article_id
    assert updated_articles[0].article_id not in {
        article.article_id for article in original_articles
    }


def test_read_article_or_404_returns_requested_duplicate_instance() -> None:
    from nook.services.viewer.content import load_viewer_page, read_article_or_404

    storage = FakeStorage()
    storage.markdowns[("tech_feed", date(2026, 4, 8))] = (
        "# Duplicate\n\nAlpha summary.\n\n---\n\n# Other\n\nBeta summary.\n\n---\n\n# Duplicate\n\nAlpha summary."
    )

    page = load_viewer_page(
        storage_backend=storage,
        target_day=date(2026, 4, 8),
        weather_data={"temp": "18", "weather_code": "100", "weather_icon": "☀️"},
    )
    requested_id = page.articles["tech_feed"][2].article_id

    article = read_article_or_404(
        storage_backend=storage,
        app_name="tech_feed",
        target_day=date(2026, 4, 8),
        article_id=requested_id,
    )

    assert article.article_id == requested_id
    assert article.title == "Duplicate"
    assert article.markdown == "# Duplicate\n\nAlpha summary."


def test_split_markdown_into_articles_discards_empty_sections_around_separators() -> (
    None
):
    from nook.services.viewer.content import split_markdown_into_articles

    articles = split_markdown_into_articles(
        app_name="tech_feed",
        markdown_text="---\n\n# First\n\nAlpha\n\n---\n\n---\n\n# Second\n\nBeta\n\n---",
    )

    assert [article.title for article in articles] == ["First", "Second"]
    assert [article.markdown for article in articles] == [
        "# First\n\nAlpha",
        "# Second\n\nBeta",
    ]


def test_read_markdown_or_404_rejects_unknown_or_missing_markdown() -> None:
    from nook.services.viewer.content import read_markdown_or_404

    payload = read_markdown_or_404(
        storage_backend=FakeStorage(),
        app_name="tech_feed",
        target_day=date(2026, 4, 8),
    )

    with pytest.raises(HTTPException) as unknown_service_error:
        read_markdown_or_404(
            storage_backend=FakeStorage(),
            app_name="viewer",
            target_day=date(2026, 4, 8),
        )

    with pytest.raises(HTTPException) as missing_markdown_error:
        read_markdown_or_404(
            storage_backend=FakeStorage(),
            app_name="tech_news",
            target_day=date(2026, 4, 8),
        )

    assert (
        payload["markdown"]
        == "# First Article\n\nAlpha summary.\n\n---\n\n# Second Article\n\nBeta summary."
    )
    assert payload["updated_at"] == "2026-04-08T00:01:00+00:00"
    assert len(payload["articles"]) == 2
    first_article = payload["articles"][0]
    second_article = payload["articles"][1]
    assert first_article["article_id"].startswith("article-tech_feed-")
    assert second_article["article_id"].startswith("article-tech_feed-")
    assert first_article["title"] == "First Article"
    assert second_article["title"] == "Second Article"
    assert (
        f'id="heading-{first_article["article_id"]}-0-first-article"'
        in first_article["html"]
    )
    assert first_article["headings"] == [
        {
            "text": "First Article",
            "anchor": f"heading-{first_article['article_id']}-0-first-article",
            "level": 1,
        }
    ]
    assert second_article["headings"] == [
        {
            "text": "Second Article",
            "anchor": f"heading-{second_article['article_id']}-1-second-article",
            "level": 1,
        }
    ]
    assert unknown_service_error.value.status_code == 404
    assert unknown_service_error.value.detail == "App not found"
    assert missing_markdown_error.value.status_code == 404
    assert missing_markdown_error.value.detail == "Markdown content not found"


def test_read_article_or_404_returns_selected_article_only() -> None:
    from nook.services.viewer.content import (
        read_article_or_404,
        split_markdown_into_articles,
    )

    article_id = split_markdown_into_articles(
        app_name="tech_feed",
        markdown_text="# First Article\n\nAlpha summary.\n\n---\n\n# Second Article\n\nBeta summary.",
    )[1].article_id

    article = read_article_or_404(
        storage_backend=FakeStorage(),
        app_name="tech_feed",
        target_day=date(2026, 4, 8),
        article_id=article_id,
    )

    with pytest.raises(HTTPException) as missing_article_error:
        read_article_or_404(
            storage_backend=FakeStorage(),
            app_name="tech_feed",
            target_day=date(2026, 4, 8),
            article_id="article-tech_feed-999",
        )

    assert article.article_id == article_id
    assert article.title == "Second Article"
    assert article.markdown == "# Second Article\n\nBeta summary."
    assert missing_article_error.value.status_code == 404
    assert missing_article_error.value.detail == "Article not found"


def test_read_markdown_or_404_rejects_stale_markdown_when_timestamp_unchanged() -> None:
    from nook.services.viewer.content import read_markdown_or_404

    with pytest.raises(HTTPException) as stale_markdown_error:
        read_markdown_or_404(
            storage_backend=FakeStorage(),
            app_name="tech_feed",
            target_day=date(2026, 4, 8),
            previous_updated_at=datetime(2026, 4, 8, 0, 1, tzinfo=timezone.utc),
        )

    assert stale_markdown_error.value.status_code == 404
    assert stale_markdown_error.value.detail == "Markdown content not found"


def test_trigger_retry_wraps_job_errors_as_http_exception() -> None:
    from nook.services.viewer.content import trigger_retry

    accepted = trigger_retry(job_invoker=FakeJobInvoker(), app_name="tech_feed")

    with pytest.raises(HTTPException) as error:
        trigger_retry(job_invoker=FailingJobInvoker(), app_name="tech_feed")

    assert (
        accepted["message"] == "Job trigger for tech_feed accepted. Processing started."
    )
    assert accepted["started_at"]
    assert error.value.status_code == 500
    assert "Failed to trigger tech_feed: boom" in error.value.detail


def test_build_chat_prompt_adds_optional_context_section() -> None:
    from nook.services.viewer.chat import build_chat_prompt

    prompt = build_chat_prompt(
        markdown="# article",
        additional_context="- Content from https://example.com:\n\n'''body'''",
        chat_history="user: hi",
        message="tell me more",
    )

    assert "[記事またはユーザーからの質問に含まれるリンクの内容]" in prompt
    assert "# article" in prompt
    assert "user: hi" in prompt
    assert "tell me more" in prompt


def test_extract_links_skips_media_label_links_and_keeps_plain_urls() -> None:
    from nook.services.viewer.chat import extract_links

    text = """
    [Article](https://example.com/article)
    [Image cover](https://example.com/image.png)
    [Video clip](https://example.com/video.mp4)
    Plain https://example.com/plain
    """

    assert extract_links(text) == [
        "https://example.com/article",
        "https://example.com/plain",
    ]


def test_collect_additional_context_deduplicates_links_and_skips_empty_content() -> (
    None
):
    from nook.services.viewer.chat import collect_additional_context

    requested: list[str] = []

    def _fetch(url: str) -> str | None:
        requested.append(url)
        if url.endswith("/article"):
            return "article body"
        return None

    context = collect_additional_context(
        markdown="[Article](https://example.com/article)",
        message="See https://example.com/article and https://example.com/empty",
        content_fetcher=_fetch,
    )

    assert requested == [
        "https://example.com/article",
        "https://example.com/empty",
    ]
    assert (
        context == "- Content from https://example.com/article:\n\n'''article body'''"
    )


def test_get_weather_data_returns_fallback_on_request_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nook.services.viewer.weather import get_weather_data

    def _raise_request_error(*args, **kwargs):
        _ = args, kwargs
        raise requests.RequestException("boom")

    monkeypatch.setattr(
        "nook.services.viewer.weather.requests.get", _raise_request_error
    )

    assert get_weather_data() == {
        "temp": "--",
        "weather_code": "100",
        "weather_icon": "☀️",
    }


def test_fetch_url_content_returns_none_on_request_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nook.services.viewer.fetch import fetch_url_content

    def _raise_request_error(*args, **kwargs):
        _ = args, kwargs
        raise requests.RequestException("boom")

    monkeypatch.setattr("nook.services.viewer.fetch.requests.get", _raise_request_error)

    assert fetch_url_content("https://example.com/article") is None
