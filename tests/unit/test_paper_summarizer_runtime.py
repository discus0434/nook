def test_paper_summarizer_uses_extended_gemini_timeout(
    monkeypatch,
) -> None:
    import nook.services.paper_summarizer.service as paper_service

    captured_kwargs: dict[str, object] = {}

    class DummyCollectorStorage:
        def __init__(self, *, service_name: str, backend: object) -> None:
            self.service_name = service_name
            self.backend = backend

        def read_state(self, key: str) -> str | None:
            _ = key
            return None

    class DummyPaperIdRetriever:
        def retrieve_from_hugging_face(self) -> list[str]:
            return []

    monkeypatch.setattr(
        paper_service,
        "create_client",
        lambda *args, **kwargs: captured_kwargs.update(kwargs) or object(),
    )
    monkeypatch.setattr(paper_service, "CollectorStorage", DummyCollectorStorage)
    monkeypatch.setattr(paper_service, "build_storage_backend", lambda env: object())
    monkeypatch.setattr(paper_service.arxiv, "Client", lambda: object())
    monkeypatch.setattr(paper_service, "PaperIdRetriever", DummyPaperIdRetriever)

    paper_service.PaperSummarizer()

    assert captured_kwargs["timeout"] == 180000


def test_paper_summarizer_uses_structured_summary_schema(monkeypatch) -> None:
    import nook.services.paper_summarizer.service as paper_service
    from nook.services.paper_summarizer.summary_schema import PaperSummarySections

    captured: dict[str, object] = {}

    class DummyClient:
        def generate_structured_content(
            self,
            *,
            contents: str,
            system_instruction: str,
            response_schema: type[object],
        ) -> PaperSummarySections:
            captured["contents"] = contents
            captured["system_instruction"] = system_instruction
            captured["response_schema"] = response_schema
            return PaperSummarySections(
                approach=["approach"],
                results=["results"],
                limitations=["limitations"],
                references=[],
            )

    class DummyCollectorStorage:
        def __init__(self, *, service_name: str, backend: object) -> None:
            self.service_name = service_name
            self.backend = backend

        def read_state(self, key: str) -> str | None:
            _ = key
            return None

    class DummyPaperIdRetriever:
        def retrieve_from_hugging_face(self) -> list[str]:
            return []

    monkeypatch.setattr(paper_service, "create_client", lambda **kwargs: DummyClient())
    monkeypatch.setattr(paper_service, "CollectorStorage", DummyCollectorStorage)
    monkeypatch.setattr(paper_service, "build_storage_backend", lambda env: object())
    monkeypatch.setattr(paper_service.arxiv, "Client", lambda: object())
    monkeypatch.setattr(paper_service, "PaperIdRetriever", DummyPaperIdRetriever)

    summarizer = paper_service.PaperSummarizer()
    paper = paper_service.PaperInfo(
        title="Structured Paper",
        abstract="Abstract",
        url="https://arxiv.org/abs/1234.56789",
        contents="Full body",
    )

    paper.summary = summarizer._summarize_paper_info(paper)
    markdown = summarizer._stylize_paper_info(paper)

    assert captured["response_schema"] is PaperSummarySections
    assert "Full body" in captured["system_instruction"]
    assert markdown.startswith("# Structured Paper")
    assert "## 1. どのようなアプローチで課題を解決しようとしたか" in markdown
    assert "- approach" in markdown


def test_paper_summarizer_stores_rendered_markdown(monkeypatch) -> None:
    import nook.services.paper_summarizer.service as paper_service
    from nook.services.paper_summarizer.summary_schema import PaperSummarySections

    captured: dict[str, object] = {}

    class DummyClient:
        def generate_structured_content(
            self,
            *,
            contents: str,
            system_instruction: str,
            response_schema: type[object],
        ) -> PaperSummarySections:
            captured["contents"] = contents
            captured["system_instruction"] = system_instruction
            captured["response_schema"] = response_schema
            return PaperSummarySections(
                approach=["approach"],
                results=["results"],
                limitations=["limitations"],
                references=[],
            )

    class DummyCollectorStorage:
        def __init__(self, *, service_name: str, backend: object) -> None:
            _ = backend
            self.service_name = service_name
            self.written_sections: list[str] = []

        def read_state(self, key: str) -> str | None:
            _ = key
            return None

        def write_state(self, key: str, content: str) -> None:
            _ = key, content

        def write_daily_markdown(
            self,
            sections: list[str],
            *,
            day: object | None = None,
            separator: str = "\n\n---\n\n",
        ) -> bool:
            _ = day, separator
            self.written_sections = list(sections)
            return True

    class DummyPaperIdRetriever:
        def retrieve_from_hugging_face(self) -> list[str]:
            return ["1234.56789"]

    class DummyExecutor:
        def __init__(self, *, max_workers: int) -> None:
            self.max_workers = max_workers

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            _ = exc_type, exc, tb
            return False

        def map(self, fn, iterable):
            return [fn(item) for item in iterable]

    monkeypatch.setattr(paper_service, "create_client", lambda **kwargs: DummyClient())
    monkeypatch.setattr(paper_service, "CollectorStorage", DummyCollectorStorage)
    monkeypatch.setattr(paper_service, "build_storage_backend", lambda env: object())
    monkeypatch.setattr(paper_service.arxiv, "Client", lambda: object())
    monkeypatch.setattr(paper_service, "PaperIdRetriever", DummyPaperIdRetriever)
    monkeypatch.setattr(
        paper_service.concurrent.futures,
        "ThreadPoolExecutor",
        DummyExecutor,
    )
    monkeypatch.setattr(paper_service, "tqdm", lambda iterable, **kwargs: iterable)

    summarizer = paper_service.PaperSummarizer()
    monkeypatch.setattr(
        summarizer,
        "_retrieve_paper_info",
        lambda arxiv_id: paper_service.PaperInfo(
            title=f"Structured Paper {arxiv_id}",
            abstract="Abstract",
            url=f"https://arxiv.org/abs/{arxiv_id}",
            contents="Full body",
        ),
    )

    summarizer()

    assert captured["response_schema"] is PaperSummarySections
    assert summarizer._storage.written_sections
    assert summarizer._storage.written_sections[0].startswith(
        "# Structured Paper 1234.56789"
    )
    assert "## 2. 結果、何が達成できたのか" in summarizer._storage.written_sections[0]
    assert "- results" in summarizer._storage.written_sections[0]
