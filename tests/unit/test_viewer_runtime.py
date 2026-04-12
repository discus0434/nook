from datetime import date, datetime, timezone

from fastapi.testclient import TestClient

from nook.services.viewer.app import create_app


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

    def write_markdown(self, service_name: str, day: date, content: str) -> None:
        self.markdowns[(service_name, day)] = content

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


class CapturingChatClient:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def chat_with_search(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return "assistant response"


def test_create_app_reads_markdown_and_triggers_local_job() -> None:
    from nook.services.viewer.content import split_markdown_into_articles

    storage = FakeStorage()
    job_invoker = FakeJobInvoker()
    article_ids = [
        article.article_id
        for article in split_markdown_into_articles(
            "tech_feed",
            storage.markdowns[("tech_feed", date(2026, 4, 8))],
        )
    ]
    app = create_app(
        storage_backend=storage,
        job_invoker=job_invoker,
        weather_provider=lambda: {
            "temp": "18",
            "weather_code": "100",
            "weather_icon": "☀️",
        },
    )
    client = TestClient(app)

    index_response = client.get("/", params={"date": "2026-04-08"})
    markdown_response = client.get(
        "/api/markdown/tech_feed",
        params={"date": "2026-04-08"},
    )
    weather_response = client.get("/api/weather")
    retry_response = client.post("/retry/tech_feed")

    assert index_response.status_code == 200
    assert "/static/viewer.css?v=" in index_response.text
    assert "/static/viewer.js?v=" in index_response.text
    assert index_response.headers["cache-control"] == "no-store"
    assert "katex.min.css" in index_response.text
    assert "api.dicebear.com/7.x/shapes/svg?seed=nook" in index_response.text
    assert 'id="scrollTopBtn"' in index_response.text
    assert (
        'class="toast-container position-fixed bottom-0 end-0 p-3"'
        in index_response.text
    )
    assert 'class="navbar"' in index_response.text
    assert 'class="sidebar-sticky"' in index_response.text
    assert 'class="nav nav-tabs"' in index_response.text
    assert 'data-app-name="tech_news"' in index_response.text
    assert index_response.text.count('class="nav-link active"') == 1
    assert 'data-app-name="tech_feed"' in index_response.text
    assert ">News<" in index_response.text
    assert ">Feeds<" in index_response.text
    assert (
        '<img src="https://api.dicebear.com/7.x/shapes/svg?seed=nook" alt="nook">'
        in index_response.text
    )
    assert ">Date<" in index_response.text
    assert ">Load<" in index_response.text
    assert ">Contents<" in index_response.text
    assert ">Retry Now<" in index_response.text
    assert "Content for 2026-04-08 not found." in index_response.text
    assert "Content for this date is not available." in index_response.text
    assert "Ask a question about this article..." not in index_response.text
    assert 'id="article-title"' not in index_response.text
    assert 'id="article-meta"' not in index_response.text
    assert "Updated 2026-04-08T00:01:00+00:00" not in index_response.text
    assert index_response.text.count('class="article-section"') == 0
    assert 'class="chat-input article-chat-form"' not in index_response.text
    assert f'data-article-id="{article_ids[0]}"' not in index_response.text
    assert f'data-article-id="{article_ids[1]}"' not in index_response.text
    assert (
        f'href="#heading-{article_ids[0]}-0-first-article"' not in index_response.text
    )
    assert "No headings" in index_response.text
    assert "Collected signals, one surface." not in index_response.text
    assert "追加調査つきで質問できます。" not in index_response.text
    assert markdown_response.status_code == 200
    markdown_payload = markdown_response.json()
    assert markdown_payload["markdown"] == (
        "# First Article\n\nAlpha summary.\n\n---\n\n# Second Article\n\nBeta summary."
    )
    assert markdown_payload["updated_at"] == "2026-04-08T00:01:00+00:00"
    assert markdown_payload["articles"] == [
        {
            "article_id": article_ids[0],
            "title": "First Article",
            "html": (
                f'<h1 class="md-heading md-h1" id="heading-{article_ids[0]}-0-first-article">'
                "First Article</h1>\n<p>Alpha summary.</p>"
            ),
            "headings": [
                {
                    "text": "First Article",
                    "anchor": f"heading-{article_ids[0]}-0-first-article",
                    "level": 1,
                }
            ],
        },
        {
            "article_id": article_ids[1],
            "title": "Second Article",
            "html": (
                f'<h1 class="md-heading md-h1" id="heading-{article_ids[1]}-1-second-article">'
                "Second Article</h1>\n<p>Beta summary.</p>"
            ),
            "headings": [
                {
                    "text": "Second Article",
                    "anchor": f"heading-{article_ids[1]}-1-second-article",
                    "level": 1,
                }
            ],
        },
    ]
    assert weather_response.status_code == 200
    assert weather_response.json()["temp"] == "18"
    assert retry_response.status_code == 202
    assert retry_response.json()["started_at"]
    assert job_invoker.triggered == ["tech_feed"]


def test_create_app_scopes_chat_to_selected_article() -> None:
    from nook.services.viewer.content import split_markdown_into_articles

    chat_client = CapturingChatClient()
    storage = FakeStorage()
    article_id = split_markdown_into_articles(
        "tech_feed",
        storage.markdowns[("tech_feed", date(2026, 4, 8))],
    )[1].article_id
    app = create_app(
        storage_backend=storage,
        job_invoker=FakeJobInvoker(),
        weather_provider=lambda: {
            "temp": "18",
            "weather_code": "100",
            "weather_icon": "☀️",
        },
        chat_client_factory=lambda: chat_client,
    )
    client = TestClient(app)

    response = client.post(
        "/chat/tech_feed",
        json={
            "article_id": article_id,
            "date": "2026-04-08",
            "chat_history": "assistant: previous answer",
            "message": "what changed?",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"response": "assistant response"}
    assert len(chat_client.prompts) == 1
    assert "# Second Article\n\nBeta summary." in chat_client.prompts[0]
    assert "# First Article\n\nAlpha summary." not in chat_client.prompts[0]
    assert "assistant: previous answer" in chat_client.prompts[0]
    assert "what changed?" in chat_client.prompts[0]


def test_create_app_keeps_distinct_duplicate_article_ids_across_reload() -> None:
    storage = FakeStorage()
    storage.markdowns[("tech_feed", date(2026, 4, 8))] = (
        "# Duplicate\n\nAlpha summary.\n\n---\n\n# Other\n\nBeta summary.\n\n---\n\n# Duplicate\n\nAlpha summary."
    )
    app = create_app(
        storage_backend=storage,
        job_invoker=FakeJobInvoker(),
        weather_provider=lambda: {
            "temp": "18",
            "weather_code": "100",
            "weather_icon": "☀️",
        },
    )
    client = TestClient(app)

    first_payload = client.get(
        "/api/markdown/tech_feed",
        params={"date": "2026-04-08"},
    ).json()

    storage.markdowns[("tech_feed", date(2026, 4, 8))] = (
        "# Duplicate\n\nAlpha summary.\n\n---\n\n# Duplicate\n\nAlpha summary.\n\n---\n\n# Other\n\nBeta summary.\n\n---\n\n# Duplicate\n\nAlpha summary."
    )

    second_payload = client.get(
        "/api/markdown/tech_feed",
        params={"date": "2026-04-08"},
    ).json()

    first_ids = [article["article_id"] for article in first_payload["articles"]]
    second_ids = [article["article_id"] for article in second_payload["articles"]]

    assert len(set(first_ids)) == 3
    assert len(set(second_ids)) == 4
    assert second_ids[1] == first_ids[0]
    assert second_ids[2] == first_ids[1]
    assert second_ids[3] == first_ids[2]
    assert second_ids[0] not in set(first_ids)


def test_create_app_server_renders_missing_state_without_javascript() -> None:
    app = create_app(
        storage_backend=FakeStorage(),
        job_invoker=FakeJobInvoker(),
        weather_provider=lambda: {
            "temp": "18",
            "weather_code": "100",
            "weather_icon": "☀️",
        },
    )
    client = TestClient(app)

    index_response = client.get("/", params={"date": "2026-04-09"})

    assert index_response.status_code == 200
    assert 'data-app-name="tech_news"' in index_response.text
    assert index_response.text.count('class="nav-link active"') == 1
    assert ">News<" in index_response.text
    assert 'data-app-name="hacker_news"' in index_response.text
    assert ">HN<" in index_response.text
    assert 'value="2026-04-09"' in index_response.text
    assert "Content for 2026-04-09 not found." in index_response.text
    assert "Content for this date is not available." in index_response.text
    assert "No headings" in index_response.text
    assert 'class="chat-input article-chat-form"' not in index_response.text


def test_create_app_returns_404_for_unknown_or_missing_markdown() -> None:
    app = create_app(
        storage_backend=FakeStorage(),
        job_invoker=FakeJobInvoker(),
        weather_provider=lambda: {
            "temp": "18",
            "weather_code": "100",
            "weather_icon": "☀️",
        },
    )
    client = TestClient(app)

    unknown_response = client.get("/api/markdown/viewer", params={"date": "2026-04-08"})
    missing_response = client.get(
        "/api/markdown/tech_news",
        params={"date": "2026-04-08"},
    )

    assert unknown_response.status_code == 404
    assert unknown_response.json() == {"detail": "App not found"}
    assert missing_response.status_code == 404
    assert missing_response.json() == {"detail": "Markdown content not found"}


def test_create_app_returns_404_for_stale_markdown_poll() -> None:
    app = create_app(
        storage_backend=FakeStorage(),
        job_invoker=FakeJobInvoker(),
        weather_provider=lambda: {
            "temp": "18",
            "weather_code": "100",
            "weather_icon": "☀️",
        },
    )
    client = TestClient(app)

    stale_response = client.get(
        "/api/markdown/tech_feed",
        params={
            "date": "2026-04-08",
            "previous_updated_at": "2026-04-08T00:01:00+00:00",
        },
    )

    assert stale_response.status_code == 404
    assert stale_response.json() == {"detail": "Markdown content not found"}


def test_create_app_returns_404_and_500_for_retry_errors() -> None:
    unknown_app = create_app(
        storage_backend=FakeStorage(),
        job_invoker=FakeJobInvoker(),
        weather_provider=lambda: {
            "temp": "18",
            "weather_code": "100",
            "weather_icon": "☀️",
        },
    )
    failing_app = create_app(
        storage_backend=FakeStorage(),
        job_invoker=FailingJobInvoker(),
        weather_provider=lambda: {
            "temp": "18",
            "weather_code": "100",
            "weather_icon": "☀️",
        },
    )

    unknown_client = TestClient(unknown_app)
    failing_client = TestClient(failing_app)

    unknown_response = unknown_client.post("/retry/viewer")
    failing_response = failing_client.post("/retry/tech_feed")

    assert unknown_response.status_code == 404
    assert unknown_response.json() == {"detail": "App not found"}
    assert failing_response.status_code == 500
    assert failing_response.json() == {"detail": "Failed to trigger tech_feed: boom"}
