from dataclasses import dataclass
from typing import Protocol


@dataclass
class CategoryResult:
    category: str
    subcategory: str
    tags: list[str]
    confidence: float
    provider: str


class LLMAdapter(Protocol):
    async def classify(self, title: str, description: str) -> CategoryResult:
        ...
