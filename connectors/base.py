from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class RawRecord:
    external_id: str
    payload: dict[str, Any]
    raw_text: str


class BaseSourceConnector(Protocol):
    source_name: str

    async def fetch(self, cursor: str | None = None) -> tuple[list[RawRecord], str | None]:
        ...
