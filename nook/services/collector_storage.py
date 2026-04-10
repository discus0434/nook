from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from nook.services.storage import StorageBackend

DEFAULT_MARKDOWN_SEPARATOR = "\n\n---\n\n"


@dataclass(slots=True)
class CollectorStorage:
    service_name: str
    backend: StorageBackend

    def write_daily_markdown(
        self,
        sections: Sequence[str],
        *,
        day: date | None = None,
        separator: str = DEFAULT_MARKDOWN_SEPARATOR,
    ) -> bool:
        if not sections:
            return False

        target_day = day or date.today()
        self.backend.write_markdown(
            service_name=self.service_name,
            day=target_day,
            content=separator.join(sections),
        )
        return True

    def read_state(self, key: str) -> str | None:
        return self.backend.read_state(self.service_name, key)

    def write_state(self, key: str, content: str) -> None:
        self.backend.write_state(self.service_name, key, content)
