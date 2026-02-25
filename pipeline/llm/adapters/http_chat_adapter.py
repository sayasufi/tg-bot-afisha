import json

import httpx

from pipeline.llm.adapters.base import CategoryResult, LLMAdapter


class HTTPChatAdapter(LLMAdapter):
    def __init__(self, base_url: str, timeout_seconds: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def classify(self, title: str, description: str) -> CategoryResult:
        prompt = (
            "Classify event type and return ONLY JSON with fields: "
            "category, subcategory, tags(array), confidence(0..1). "
            "Categories: concert,theatre,exhibition,standup,festival,lecture,kids,other."
        )
        payload = {
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Title: {title}\nDescription: {description}"},
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
            parsed = json.loads(raw_content)
        except (json.JSONDecodeError, TypeError):
            parsed = {}

        return CategoryResult(
            category=parsed.get("category", "other"),
            subcategory=parsed.get("subcategory", ""),
            tags=parsed.get("tags", []),
            confidence=float(parsed.get("confidence", 0.5)),
            provider="http-chat",
        )
