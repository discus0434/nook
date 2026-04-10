from datetime import date
from pathlib import Path

from nook.services.paper_summarizer import service as paper_service
from nook.services.storage import FilesystemStorageBackend


class _FixedDate(date):
    @classmethod
    def today(cls) -> "_FixedDate":
        return cls(2026, 4, 8)


def test_paper_summarizer_uses_storage_backend_for_state(
    monkeypatch,
    tmp_path: Path,
) -> None:
    backend = FilesystemStorageBackend(data_dir=tmp_path)
    backend.write_state(
        "paper_summarizer",
        "arxiv_ids-2026-04-07.txt",
        "1234.56789\n",
    )

    monkeypatch.setattr(paper_service, "build_storage_backend", lambda env: backend)
    monkeypatch.setattr(paper_service, "create_client", lambda **kwargs: object())
    monkeypatch.setattr(paper_service.arxiv, "Client", lambda: object())
    monkeypatch.setattr(paper_service, "date", _FixedDate)

    summarizer = paper_service.PaperSummarizer()

    assert summarizer._old_arxiv_ids == ["1234.56789"]

    summarizer._save_arxiv_ids(["9999.99999"])

    assert (
        backend.read_state("paper_summarizer", "arxiv_ids-2026-04-08.txt")
        == "9999.99999"
    )
