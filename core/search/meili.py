"""Thin async Meilisearch client over httpx (no extra dependency).

Meilisearch gives the typeahead what Postgres trigram couldn't cheaply: diacritics folding
(ö→o, so "omanko" finds "Ömankö"), typo-tolerance, and prefix instant-search ranking. The
index is a denormalised mirror of active events kept fresh by a reindex flow. Disabled by
default (settings.meili_search_enabled) → the API falls back to the Postgres search, so the
service being down or absent never breaks search.

A reindex builds a throwaway `<index>_tmp`, fills it, then atomically swaps it with the live
index — so the live index is never empty mid-reindex (zero-downtime).
"""
import httpx

from core.config.settings import get_settings

# searchableAttributes order is also a tiebreaker: a title hit outranks a venue hit. title_translit
# lets a latin query find a Cyrillic title ("bolshoi" → "Большой"); diacritics are folded natively.
INDEX_SETTINGS = {
    "searchableAttributes": ["title", "title_translit", "venue", "code"],
    # _geo lets us reuse the existing city-radius scoping via Meili's _geoRadius filter.
    "filterableAttributes": ["_geo", "status"],
    "sortableAttributes": ["date_start_ts"],
    "rankingRules": ["words", "typo", "proximity", "attribute", "sort", "exactness"],
    "typoTolerance": {"enabled": True, "minWordSizeForTypos": {"oneTypo": 4, "twoTypos": 8}},
}
_BATCH = 1000


class MeiliClient:
    def __init__(self) -> None:
        s = get_settings()
        self.base = s.meili_url.rstrip("/")
        self.index = s.meili_index
        self.timeout = httpx.Timeout(connect=5.0, read=15.0, write=15.0, pool=5.0)
        self._headers = {"Authorization": f"Bearer {s.meili_master_key}"} if s.meili_master_key else {}

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base, headers=self._headers, timeout=self.timeout)

    async def _ensure(self, client: httpx.AsyncClient, uid: str) -> None:
        # POST /indexes is idempotent enough: 201 created, or 4xx "index_already_exists" — both fine.
        await client.post("/indexes", json={"uid": uid, "primaryKey": "id"})
        r = await client.patch(f"/indexes/{uid}/settings", json=INDEX_SETTINGS)
        r.raise_for_status()

    async def ensure_index(self) -> None:
        async with self._client() as client:
            await self._ensure(client, self.index)

    async def reindex(self, docs: list[dict]) -> int:
        """Atomically replace the whole index with `docs` via a tmp-index swap (no empty window)."""
        tmp = f"{self.index}_tmp"
        async with self._client() as client:
            await self._ensure(client, self.index)  # live index must exist for the swap
            await self._ensure(client, tmp)
            await client.delete(f"/indexes/{tmp}/documents")  # clear leftovers from a prior run
            for i in range(0, len(docs), _BATCH):
                r = await client.post(f"/indexes/{tmp}/documents", json=docs[i : i + _BATCH])
                r.raise_for_status()
            # Tasks process FIFO, so this swap runs after the adds above complete.
            r = await client.post("/swap-indexes", json=[{"indexes": [self.index, tmp]}])
            r.raise_for_status()
        return len(docs)

    async def search(
        self, q: str, *, filter: str | None = None, limit: int = 10, sort: list[str] | None = None
    ) -> list[dict]:
        body: dict = {"q": q, "limit": limit}
        if filter:
            body["filter"] = filter
        if sort:
            body["sort"] = sort
        async with self._client() as client:
            r = await client.post(f"/indexes/{self.index}/search", json=body)
            r.raise_for_status()
            return r.json().get("hits", [])
