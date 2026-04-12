def test_reddit_explorer_uses_structured_summary_schema(monkeypatch) -> None:
    import nook.services.reddit_explorer.service as reddit_service
    from nook.services.reddit_explorer.summary_schema import RedditPostSummary

    captured: dict[str, object] = {}

    class DummyClient:
        def generate_structured_content(
            self,
            *,
            contents: str,
            system_instruction: str,
            response_schema: type[object],
        ) -> RedditPostSummary:
            captured["contents"] = contents
            captured["system_instruction"] = system_instruction
            captured["response_schema"] = response_schema
            return RedditPostSummary(
                post_summary=["summary"],
                interesting_comments=["comment"],
            )

    class DummyCollectorStorage:
        def __init__(self, *, service_name: str, backend: object) -> None:
            self.service_name = service_name
            self.backend = backend

    monkeypatch.setattr(reddit_service, "create_client", lambda **kwargs: DummyClient())
    monkeypatch.setattr(
        reddit_service,
        "CollectorStorage",
        DummyCollectorStorage,
    )
    monkeypatch.setattr(
        reddit_service,
        "build_storage_backend",
        lambda env: object(),
    )
    monkeypatch.setattr(
        reddit_service,
        "require_runtime_secret",
        lambda key: f"secret-for-{key}",
    )
    monkeypatch.setattr(reddit_service.praw, "Reddit", lambda **kwargs: object())
    monkeypatch.setattr(
        reddit_service.Config,
        "load_subreddits",
        classmethod(lambda cls: ["python"]),
    )

    explorer = reddit_service.RedditExplorer()
    post = reddit_service.RedditPost(
        type="image",
        id="abc",
        title="Interesting Post",
        url="https://example.com/image.png",
        upvotes=123,
        text="selftext",
    )
    post.permalink = "https://reddit.com/r/test/post"
    post.comments = [{"text": "comment body", "upvotes": 5}]

    post.summary = explorer._summarize_reddit_post(post)
    markdown = explorer._stylize_post(post)

    assert captured["response_schema"] is RedditPostSummary
    assert "comment body" in captured["system_instruction"]
    assert "以下の2つの質問" not in captured["contents"]
    assert markdown.startswith("# Interesting Post")
    assert "## 1. このポストの内容" in markdown
    assert "- summary" in markdown


def test_reddit_explorer_stores_rendered_markdown(monkeypatch) -> None:
    import nook.services.reddit_explorer.service as reddit_service
    from nook.services.reddit_explorer.summary_schema import RedditPostSummary

    captured: dict[str, object] = {}

    class DummyClient:
        def generate_structured_content(
            self,
            *,
            contents: str,
            system_instruction: str,
            response_schema: type[object],
        ) -> RedditPostSummary:
            captured["contents"] = contents
            captured["system_instruction"] = system_instruction
            captured["response_schema"] = response_schema
            return RedditPostSummary(
                post_summary=["summary"],
                interesting_comments=["comment"],
            )

    class DummyCollectorStorage:
        def __init__(self, *, service_name: str, backend: object) -> None:
            _ = backend
            self.service_name = service_name
            self.written_sections: list[str] = []
            self.separator: str | None = None

        def write_daily_markdown(
            self,
            sections: list[str],
            *,
            day: object | None = None,
            separator: str = "\n\n---\n\n",
        ) -> bool:
            _ = day
            self.written_sections = list(sections)
            self.separator = separator
            return True

    monkeypatch.setattr(reddit_service, "create_client", lambda **kwargs: DummyClient())
    monkeypatch.setattr(
        reddit_service,
        "CollectorStorage",
        DummyCollectorStorage,
    )
    monkeypatch.setattr(
        reddit_service,
        "build_storage_backend",
        lambda env: object(),
    )
    monkeypatch.setattr(
        reddit_service,
        "require_runtime_secret",
        lambda key: f"secret-for-{key}",
    )
    monkeypatch.setattr(reddit_service.praw, "Reddit", lambda **kwargs: object())
    monkeypatch.setattr(
        reddit_service.Config,
        "load_subreddits",
        classmethod(lambda cls: ["python", "MachineLearning"]),
    )
    monkeypatch.setattr(
        reddit_service.RedditExplorer,
        "_retrieve_hot_posts",
        lambda self, subreddit: (
            [
                reddit_service.RedditPost(
                    type="text",
                    id="python-low",
                    title="Python Low",
                    url=None,
                    upvotes=5,
                    text="selftext",
                ),
                reddit_service.RedditPost(
                    type="text",
                    id="python-high",
                    title="Python High",
                    url=None,
                    upvotes=80,
                    text="selftext",
                ),
            ]
            if subreddit == "python"
            else [
                reddit_service.RedditPost(
                    type="text",
                    id="ml-mid",
                    title="ML Mid",
                    url=None,
                    upvotes=30,
                    text="selftext",
                )
            ]
        ),
    )
    monkeypatch.setattr(
        reddit_service.RedditExplorer,
        "_retrieve_top_comments_of_post",
        lambda self, post_id: [{"text": f"{post_id} comment body", "upvotes": 5}],
    )
    monkeypatch.setattr(reddit_service.time, "sleep", lambda seconds: None)

    explorer = reddit_service.RedditExplorer()
    explorer()

    assert captured["response_schema"] is RedditPostSummary
    assert explorer._storage.separator == "\n---\n"
    assert explorer._storage.written_sections
    assert [
        section.splitlines()[0] for section in explorer._storage.written_sections
    ] == [
        "# Python High",
        "# ML Mid",
        "# Python Low",
    ]
    assert "## 2. 特に興味深いコメント" in explorer._storage.written_sections[0]
    assert "- comment" in explorer._storage.written_sections[0]
