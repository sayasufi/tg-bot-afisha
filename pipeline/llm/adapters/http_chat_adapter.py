import json

import httpx

from pipeline.llm.adapters.base import CATEGORIES, CategoryResult, LLMAdapter
from pipeline.llm.json_utils import parse_llm_json

# Source-agnostic classification prompt. The category is decided by the ACTIVITY,
# with any source labels passed in as hints and reconciled into our fixed list.
_SYSTEM_PROMPT = (
    "You classify cultural events for a Moscow city map. "
    "Return ONLY a JSON object with fields: category, subcategory, tags (array of short Russian keywords), confidence (0..1). "
    "Pick EXACTLY ONE category from this fixed list: " + ", ".join(CATEGORIES) + ". "
    "Meaning of each: "
    "concert=живая музыка/концерт; theatre=спектакль/опера/балет/мюзикл; "
    "exhibition=выставка/музейная экспозиция/интерактивное пространство, которое ОСМАТРИВАЮТ (в т.ч. научно-популярное); "
    "cinema=кинопоказ/фильм/киноклуб; standup=стендап/комедийный концерт; "
    "festival=фестиваль/ярмарка/большой open-air; lecture=лекция/семинар/образовательный курс/дискуссия; "
    "tour=экскурсия/прогулка/тур/смотровая; party=вечеринка/дискотека/квиз/викторина/знакомства; "
    "quest=квест/эскейп-рум/перформанс-игра/иммерсивное приключение; "
    "kids=мероприятие явно для детей/всей семьи; other=только если ничего не подходит. "
    "RULES: classify by what people DO, not by the venue name — например свидание, квест или вечеринка В МУЗЕЕ это НЕ exhibition. "
    "Source hints (the source's own categories/tags) are the STRONGEST evidence — if a hint matches a category, prefer it. "
    "НЕ относи к lecture всё подряд: упоминание мастер-класса/«научиться» НЕ делает мероприятие лекцией. "
    "Если это пространство/выставка/аттракцион, которые осматривают или посещают (даже с активностями) → exhibition; "
    "если явно для детей или всей семьи → kids. "
    "Use 'kids' when the event is for children or families. Be decisive; avoid 'other' unless truly unclear."
)


class HTTPChatAdapter(LLMAdapter):
    def __init__(self, base_url: str, timeout_seconds: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def classify(self, title: str, description: str, hints: list[str] | None = None) -> CategoryResult:
        # Drop our own internal markers from the hints; keep raw source labels.
        clean_hints = [h for h in (hints or []) if h and not h.startswith("category:")]
        hint_line = f"\nSource hints: {', '.join(clean_hints[:20])}" if clean_hints else ""
        user = f"Title: {title}\nDescription: {(description or '')[:600]}{hint_line}"
        payload = {
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "temperature": 0.2,
            "max_tokens": 300,
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()

        raw_content = data.get("response") or "{}"
        try:
            parsed = parse_llm_json(raw_content)
        except (json.JSONDecodeError, TypeError):
            parsed = {}
        if not isinstance(parsed, dict):
            parsed = {}

        category = str(parsed.get("category", "other")).strip().lower()
        if category not in CATEGORIES:
            category = "other"
        tags = parsed.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        return CategoryResult(
            category=category,
            subcategory=str(parsed.get("subcategory", "")),
            tags=[str(t) for t in tags][:12],
            confidence=float(parsed.get("confidence", 0.5) or 0.5),
            provider="http-chat",
        )
