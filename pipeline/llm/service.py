from core.config.settings import get_settings
from pipeline.llm.adapters.base import CategoryResult
from pipeline.llm.adapters.http_chat_adapter import HTTPChatAdapter


class LLMService:
    def __init__(self) -> None:
        settings = get_settings()
        self.adapter = HTTPChatAdapter(
            base_url=settings.llm_api_base_url,
            timeout_seconds=settings.llm_timeout_seconds,
        )

    async def classify(self, title: str, description: str) -> CategoryResult:
        try:
            return await self.adapter.classify(title, description)
        except Exception:
            return CategoryResult(category="other", subcategory="", tags=[], confidence=0.0, provider="fallback")
