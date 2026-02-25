import httpx


class ApiClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def search(self, q: str, city: str | None = None, limit: int = 5) -> list[dict]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(f"{self.base_url}/v1/search", json={"q": q, "city": city, "limit": limit})
            response.raise_for_status()
            data = response.json()
            return data.get("items", [])
