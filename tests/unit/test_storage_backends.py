from datetime import date
from pathlib import Path

import pytest

from nook.services.storage import (
    FilesystemStorageBackend,
    S3StorageBackend,
    build_storage_backend,
)


def test_filesystem_storage_backend_round_trips_markdown_and_state(
    tmp_path: Path,
) -> None:
    backend = FilesystemStorageBackend(data_dir=tmp_path)

    backend.write_markdown(
        service_name="tech_feed",
        day=date(2026, 4, 8),
        content="hello markdown",
    )
    backend.write_state(
        service_name="paper_summarizer",
        key="arxiv_ids-2026-04-08.txt",
        content="1234.56789\n",
    )

    assert backend.read_markdown("tech_feed", date(2026, 4, 8)) == "hello markdown"
    record = backend.read_markdown_record("tech_feed", date(2026, 4, 8))
    assert record is not None
    assert record.content == "hello markdown"
    assert record.updated_at is not None
    assert (
        backend.read_state("paper_summarizer", "arxiv_ids-2026-04-08.txt")
        == "1234.56789\n"
    )
    assert (tmp_path / "tech_feed" / "2026-04-08.md").exists()
    assert (
        tmp_path / "_state" / "paper_summarizer" / "arxiv_ids-2026-04-08.txt"
    ).exists()


def test_filesystem_storage_backend_returns_none_for_missing_values(
    tmp_path: Path,
) -> None:
    backend = FilesystemStorageBackend(data_dir=tmp_path)

    assert backend.read_markdown("tech_feed", date(2026, 4, 8)) is None
    assert backend.read_markdown_record("tech_feed", date(2026, 4, 8)) is None
    assert backend.read_state("paper_summarizer", "missing.txt") is None


def test_build_storage_backend_requires_needed_configuration(tmp_path: Path) -> None:
    backend = build_storage_backend(
        {
            "NOOK_STORAGE_BACKEND": "filesystem",
            "NOOK_DATA_DIR": str(tmp_path),
        }
    )
    assert isinstance(backend, FilesystemStorageBackend)

    with pytest.raises(ValueError, match="BUCKET_NAME"):
        build_storage_backend({"NOOK_STORAGE_BACKEND": "s3"})


def test_s3_storage_backend_initializes_boto_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nook.services.storage as storage

    fake_client = object()
    monkeypatch.setattr(storage.boto3, "client", lambda service_name: fake_client)

    backend = S3StorageBackend(bucket_name="bucket-name")

    assert backend._client is fake_client
