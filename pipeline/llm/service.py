from core.config.settings import get_settings
from pipeline.llm.adapters.base import CategoryResult
from pipeline.llm.adapters.openai_adapter import OpenAIAdapter
from pipeline.llm.adapters.yandex_adapter import YandexAdapter


class LLMService:
    def __init__(self) -> None:
        settings = get_settings()
        self.provider = settings.llm_provider.lower()
        if self.provider == "yandex":
            self.adapter = YandexAdapter(settings.yandexgpt_api_key)
        else:
            self.adapter = OpenAIAdapter(settings.openai_api_key) if settings.openai_api_key else YandexAdapter("")

    async def classify(self, title: str, description: str) -> CategoryResult:
        try:
            return await self.adapter.classify(title, description)
        except Exception:
            return CategoryResult(category="other", subcategory="", tags=[], confidence=0.0, provider="fallback")
