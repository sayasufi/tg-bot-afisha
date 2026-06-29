import json

import httpx

from core.services.llm_limiter import llm_slot
from pipeline.llm.adapters.base import CATEGORIES, CategoryResult, LLMAdapter
from pipeline.llm.json_utils import parse_llm_json

# Classification prompt. Category is decided by the visitor's main ACTIVITY.
# This is the FALLBACK path: structured sources are mapped deterministically
# upstream (core.domain.categorization), so the LLM mostly sees untyped events and
# free-text Telegram posts — hence the explicit definitions, decision order and
# worked examples that target the failure modes we actually saw (master-class →
# wrongly "lecture", interactive/kids spaces → wrongly "lecture/exhibition").
_SYSTEM_PROMPT = (
    "Ты — точный классификатор событий для карты Москвы. "
    "Верни ТОЛЬКО JSON-объект (без markdown, без пояснений): "
    '{"category":"<одна категория>","subcategory":"","tags":["короткие русские ключевые слова"],"confidence":0..1}. '
    "category — РОВНО ОДНА из фиксированного списка: " + ", ".join(CATEGORIES) + ".\n"
    "Значение категорий (по главному ДЕЙСТВИЮ посетителя):\n"
    "- concert: живой концерт, живая музыка любого жанра.\n"
    "- theatre: спектакль, опера, балет, мюзикл, иммерсивный театр.\n"
    "- exhibition: выставка, музейная экспозиция, арт- или научно-популярное/интерактивное пространство, "
    "которое ОСМАТРИВАЮТ или ПОСЕЩАЮТ (даже если внутри есть активности или мастер-классы).\n"
    "- cinema: кинопоказ, фильм, киноклуб.\n"
    "- standup: стендап, комедийный концерт, открытый микрофон.\n"
    "- festival: фестиваль, ярмарка, городской праздник, большой open-air.\n"
    "- lecture: лекция, семинар, дискуссия, образовательный курс, отдельный мастер-класс — "
    "когда СУТЬ в том, чтобы слушать/учиться.\n"
    "- tour: экскурсия, прогулка, тур, смотровая площадка.\n"
    "- party: вечеринка, дискотека, квиз, викторина, нетворкинг/знакомства.\n"
    "- quest: квест, эскейп-рум, иммерсивная игра-приключение, перформанс-игра.\n"
    "- kids: событие ЯВНО для детей или всей семьи (возраст «0+/6+», «для детей», "
    "детский спектакль/мастер-класс, контактный зоопарк, семейный парк).\n"
    "- other: только если НИЧЕГО не подходит.\n"
    "ПОРЯДОК РЕШЕНИЯ (если подходит несколько):\n"
    "1) Если событие явно для детей или всей семьи → kids (даже если это спектакль/концерт/выставка для детей).\n"
    "2) Иначе — по главному ДЕЙСТВИЮ: осматривать экспозицию → exhibition; смотреть спектакль → theatre; "
    "слушать концерт → concert; проходить квест → quest; слушать лекцию → lecture; и т.д.\n"
    "3) Source hints (категории/теги источника) — сильнейшая подсказка: если хинт совпадает с категорией, бери её.\n"
    "ВАЖНЫЕ ПРАВИЛА (частые ошибки):\n"
    "- Классифицируй по тому, что ЛЮДИ ДЕЛАЮТ, а не по площадке: свидание/квест/вечеринка В МУЗЕЕ — это НЕ exhibition.\n"
    "- Слова «мастер-класс»/«научиться»/«погрузиться»/«узнать» в описании НЕ делают событие лекцией. "
    "lecture — только если ГЛАВНОЕ это слушать/учиться. Интерактивное или научное пространство, "
    "которое ОСМАТРИВАЮТ → exhibition; если оно для детей → kids.\n"
    "- Будь решительным: избегай other, если есть хоть одна подходящая категория.\n"
    "ПРИМЕРЫ:\n"
    'Title: Городская ферма | Описание: контактная ферма, 70 животных, можно покормить, мастер-классы, дети до 3 бесплатно, 0+ → {"category":"kids"}\n'
    'Title: Фрида Кало. Роман с болью | Описание: выставка работ художницы → {"category":"exhibition"}\n'
    'Title: Почему светятся медузы? | Описание: интерактивная научная экспозиция для детей 6+ → {"category":"kids"}\n'
    'Title: Квест «Побег из лаборатории» | Описание: командная игра на 60 минут с загадками → {"category":"quest"}\n'
    'Title: Лекция о творчестве Ван Гога | Описание: искусствовед расскажет о биографии художника → {"category":"lecture"}\n'
    'Title: Вечеринка в честь Хэллоуина | Описание: диджей-сет, дискотека до утра, 18+ → {"category":"party"}'
)


# Dedup judge: two events already proven to share a venue AND an exact start time
# (the blocking the caller does). The only question is whether the two TITLES name
# the same event — so the prior is "same", and the model just rules out genuinely
# different works/programmes that happen to collide on the same stage+minute.
_SAME_EVENT_PROMPT = (
    "Два анонса проходят на ОДНОЙ площадке в ОДНО И ТО ЖЕ время. Реши, одно ли это "
    "и то же событие (на оба названия — один и тот же показ/билет) или РАЗНЫЕ события.\n"
    "ОДНО И ТО ЖЕ, если названия отличаются лишь: сокращением/инициалами "
    "(«В.С. Локтева» = «Локтева»), склонением («Ансамбль» = «Ансамбля»), "
    "транслитерацией/переводом, регистром, пунктуацией, словом-обёрткой («Концерт …», "
    "«… сольный концерт», «… шоу»), названием площадки/города в заголовке, "
    "подзаголовком или приставкой с именем артиста.\n"
    "РАЗНЫЕ, если это разные произведения, программы, артисты или составы — даже в "
    "одном жанре («Лебединое озеро» ≠ «Щелкунчик»; «Большой стендап» ≠ «Женский стендап»).\n"
    'Верни ТОЛЬКО JSON, без пояснений: {"same": true|false, "confidence": 0..1}.'
)


class HTTPChatAdapter(LLMAdapter):
    def __init__(self, base_url: str, timeout_seconds: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def _chat(self, payload: dict) -> dict:
        """POST to the LLM endpoint while holding ONE service-wide concurrency slot (see core.services.llm_limiter)."""
        async with llm_slot():
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
                response.raise_for_status()
                return response.json()

    async def judge_same_event(self, title_a: str, title_b: str) -> tuple[bool, float]:
        """Ask whether two same-venue+same-time titles are one event. Returns
        (same, confidence). Raises on transport error (caller decides the fallback)."""
        payload = {
            "messages": [
                {"role": "system", "content": _SAME_EVENT_PROMPT},
                {"role": "user", "content": f"A: {title_a}\nB: {title_b}"},
            ],
            "stream": False,
            "temperature": 0.0,
            "max_tokens": 60,
        }
        data = await self._chat(payload)
        try:
            parsed = parse_llm_json(data.get("response") or "{}")
        except (json.JSONDecodeError, TypeError):
            parsed = {}
        if not isinstance(parsed, dict):
            parsed = {}
        try:
            conf = float(parsed.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            conf = 0.0
        return bool(parsed.get("same")), conf

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
        data = await self._chat(payload)

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
