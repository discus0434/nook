from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol

import boto3
from botocore.exceptions import ClientError


@dataclass(frozen=True, slots=True)
class MarkdownRecord:
    content: str
    updated_at: datetime | None


class StorageBackend(Protocol):
    def read_markdown_record(
        self,
        service_name: str,
        day: date,
    ) -> MarkdownRecord | None: ...

    def read_markdown(self, service_name: str, day: date) -> str | None: ...

    def write_markdown(self, service_name: str, day: date, content: str) -> None: ...

    def read_state(self, service_name: str, key: str) -> str | None: ...

    def write_state(self, service_name: str, key: str, content: str) -> None: ...


@dataclass(slots=True)
class FilesystemStorageBackend:
    data_dir: Path

    def read_markdown_record(
        self,
        service_name: str,
        day: date,
    ) -> MarkdownRecord | None:
        path = self._markdown_path(service_name, day)
        if not path.exists():
            return None
        return MarkdownRecord(
            content=path.read_text(encoding="utf-8"),
            updated_at=datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc),
        )

    def read_markdown(self, service_name: str, day: date) -> str | None:
        record = self.read_markdown_record(service_name, day)
        if record is None:
            return None
        return record.content

    def write_markdown(self, service_name: str, day: date, content: str) -> None:
        path = self._markdown_path(service_name, day)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def read_state(self, service_name: str, key: str) -> str | None:
        path = self._state_path(service_name, key)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def write_state(self, service_name: str, key: str, content: str) -> None:
        path = self._state_path(service_name, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _markdown_path(self, service_name: str, day: date) -> Path:
        return self.data_dir / service_name / f"{day.isoformat()}.md"

    def _state_path(self, service_name: str, key: str) -> Path:
        return self.data_dir / "_state" / service_name / key


@dataclass(slots=True)
class S3StorageBackend:
    bucket_name: str
    _client: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._client = boto3.client("s3")

    def read_markdown_record(
        self,
        service_name: str,
        day: date,
    ) -> MarkdownRecord | None:
        response = self._read_object(f"{service_name}/{day.isoformat()}.md")
        if response is None:
            return None
        updated_at = response.get("LastModified")
        if isinstance(updated_at, datetime):
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            else:
                updated_at = updated_at.astimezone(timezone.utc)
        else:
            updated_at = None
        return MarkdownRecord(
            content=response["Body"].read().decode("utf-8"),
            updated_at=updated_at,
        )

    def read_markdown(self, service_name: str, day: date) -> str | None:
        record = self.read_markdown_record(service_name, day)
        if record is None:
            return None
        return record.content

    def write_markdown(self, service_name: str, day: date, content: str) -> None:
        self._client.put_object(
            Bucket=self.bucket_name,
            Key=f"{service_name}/{day.isoformat()}.md",
            Body=content.encode("utf-8"),
            ContentType="text/markdown; charset=utf-8",
        )

    def read_state(self, service_name: str, key: str) -> str | None:
        return self._read_text(f"_state/{service_name}/{key}")

    def write_state(self, service_name: str, key: str, content: str) -> None:
        self._client.put_object(
            Bucket=self.bucket_name,
            Key=f"_state/{service_name}/{key}",
            Body=content.encode("utf-8"),
            ContentType="text/plain; charset=utf-8",
        )

    def _read_text(self, key: str) -> str | None:
        response = self._read_object(key)
        if response is None:
            return None
        return response["Body"].read().decode("utf-8")

    def _read_object(self, key: str) -> dict[str, object] | None:
        try:
            response = self._client.get_object(Bucket=self.bucket_name, Key=key)
        except ClientError as error:
            error_code = error.response.get("Error", {}).get("Code")
            if error_code in {"NoSuchKey", "404"}:
                return None
            raise

        return response


def build_storage_backend(env: Mapping[str, str | None]) -> StorageBackend:
    backend_name = env.get("NOOK_STORAGE_BACKEND")
    if backend_name is None:
        backend_name = "s3" if env.get("BUCKET_NAME") else "filesystem"

    if backend_name == "filesystem":
        data_dir = env.get("NOOK_DATA_DIR")
        if not data_dir:
            data_dir = str(Path.home() / ".local" / "share" / "my-nook" / "data")
        return FilesystemStorageBackend(data_dir=Path(data_dir))

    if backend_name == "s3":
        bucket_name = env.get("BUCKET_NAME")
        if not bucket_name:
            raise ValueError("BUCKET_NAME is required for s3 storage backend")
        return S3StorageBackend(bucket_name=bucket_name)

    raise ValueError(f"Unsupported storage backend: {backend_name}")
