import httpx


class ApiClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def search_events(self, q: str, limit: int = 6) -> list[dict]:
        """Search via the map endpoint so results carry category/date/venue/price."""
        params = {"q": q, "limit": limit}
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{self.base_url}/v1/events/map", params=params)
            response.raise_for_status()
            return response.json().get("items", [])

    async def categories(self) -> list[str]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{self.base_url}/v1/categories")
            response.raise_for_status()
            return response.json().get("categories", [])
