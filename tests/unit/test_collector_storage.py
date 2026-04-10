from datetime import date
from pathlib import Path

from nook.services.collector_storage import CollectorStorage
from nook.services.storage import FilesystemStorageBackend


def test_collector_storage_writes_daily_markdown_with_default_separator(
    tmp_path: Path,
) -> None:
    storage = CollectorStorage(
        service_name="tech_news",
        backend=FilesystemStorageBackend(data_dir=tmp_path),
    )

    wrote = storage.write_daily_markdown(
        ["first summary", "second summary"],
        day=date(2026, 4, 8),
    )

    assert wrote is True
    assert (tmp_path / "tech_news" / "2026-04-08.md").read_text(
        encoding="utf-8"
    ) == "first summary\n\n---\n\nsecond summary"


def test_collector_storage_skips_empty_daily_markdown(tmp_path: Path) -> None:
    storage = CollectorStorage(
        service_name="tech_news",
        backend=FilesystemStorageBackend(data_dir=tmp_path),
    )

    wrote = storage.write_daily_markdown([], day=date(2026, 4, 8))

    assert wrote is False
    assert not (tmp_path / "tech_news" / "2026-04-08.md").exists()


def test_collector_storage_round_trips_state(tmp_path: Path) -> None:
    storage = CollectorStorage(
        service_name="paper_summarizer",
        backend=FilesystemStorageBackend(data_dir=tmp_path),
    )

    storage.write_state("arxiv_ids-2026-04-08.txt", "1234.56789\n")

    assert storage.read_state("arxiv_ids-2026-04-08.txt") == "1234.56789\n"
