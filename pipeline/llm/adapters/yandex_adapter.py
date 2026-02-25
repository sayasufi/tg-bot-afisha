from pipeline.llm.adapters.base import CategoryResult, LLMAdapter


class YandexAdapter(LLMAdapter):
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    async def classify(self, title: str, description: str) -> CategoryResult:
        # Stub adapter for MVP skeleton; replace with real YandexGPT API call.
        lowered = f"{title} {description}".lower()
        category = "other"
        if "concert" in lowered or "jazz" in lowered:
            category = "concert"
        elif "theatre" in lowered or "theater" in lowered:
            category = "theatre"
        elif "exhibition" in lowered:
            category = "exhibition"
        return CategoryResult(category=category, subcategory="", tags=[], confidence=0.5, provider="yandex")
