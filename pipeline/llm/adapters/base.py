from dataclasses import dataclass
from typing import Protocol


@dataclass
class CategoryResult:
    category: str
    subcategory: str
    tags: list[str]
    confidence: float
    provider: str


# The fixed taxonomy every source must be mapped into. Source-agnostic: the LLM
# reconciles any source's own labels (passed as hints) into exactly one of these.
CATEGORIES = (
    "concert",
    "theatre",
    "exhibition",
    "cinema",
    "standup",
    "festival",
    "lecture",
    "tour",
    "party",
    "quest",
    "kids",
    "other",
)


class LLMAdapter(Protocol):
    async def classify(self, title: str, description: str, hints: list[str] | None = None) -> CategoryResult:
        ...
