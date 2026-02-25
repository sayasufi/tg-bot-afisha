import json

from openai import AsyncOpenAI

from pipeline.llm.adapters.base import CategoryResult, LLMAdapter


class OpenAIAdapter(LLMAdapter):
    def __init__(self, api_key: str) -> None:
        self.client = AsyncOpenAI(api_key=api_key)

    async def classify(self, title: str, description: str) -> CategoryResult:
        prompt = (
            "Classify event type and return JSON with fields: category, subcategory, tags(array), confidence(0..1). "
            "Categories: concert,theatre,exhibition,standup,festival,lecture,kids,other."
        )
        resp = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Title: {title}\nDescription: {description}"},
            ],
            timeout=20.0,
        )
        text = resp.choices[0].message.content or "{}"
        data = json.loads(text)
        return CategoryResult(
            category=data.get("category", "other"),
            subcategory=data.get("subcategory", ""),
            tags=data.get("tags", []),
            confidence=float(data.get("confidence", 0.5)),
            provider="openai",
        )
