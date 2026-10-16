from __future__ import annotations

import re
from typing import Any

from .client import BaonlyClient, is_event_id
from .errors import ApiError, EventNotFound
from .mapping import map_list_item
from .query import EventQuery

_FIELD_WEIGHTS = (
    ("title", 60),
    ("organizer", 45),
    ("city", 35),
    ("province", 30),
    ("venueName", 25),
    ("address", 20),
)
_EXACT_BONUS = 40
_TAG_SCORE = 15
_PER_TOKEN_BONUS = 20
_STATE_BONUS = {"ongoing": 8, "upcoming": 5}
_FALLBACK_LIMIT = 2000


def _tokens(query: str) -> list[str]:
    return [t for t in re.split(r"[\s,，、]+", query.lower()) if t]


def score(event: dict[str, Any], tokens: list[str]) -> int:
    values = {key: str(event.get(key) or "").lower() for key, _ in _FIELD_WEIGHTS}
    tags = " ".join(str(t) for t in event.get("tags") or []).lower()

    matched = total = 0
    for token in tokens:
        best = 0
        for key, weight in _FIELD_WEIGHTS:
            value = values[key]
            if value == token:
                best = max(best, weight + _EXACT_BONUS)
            elif value and token in value:
                best = max(best, weight)
        if not best and token in tags:
            best = _TAG_SCORE
        if best:
            matched += 1
            total += best

    if not matched:
        return 0
    return total + matched * _PER_TOKEN_BONUS + _STATE_BONUS.get(event.get("state") or "", 0)


class EventSearch:
    def __init__(self, client: BaonlyClient):
        self._client = client

    async def resolve(self, query: str) -> dict[str, Any] | None:
        query = (query or "").strip()
        if not query:
            return None

        if is_event_id(query):
            try:
                return await self._client.get_event(query)
            except EventNotFound:
                pass

        tokens = _tokens(query)
        candidates = await self._candidates(query)
        ranked = sorted(((score(c, tokens), c) for c in candidates), key=lambda p: p[0], reverse=True)
        if not ranked or ranked[0][0] <= 0:
            return None
        try:
            return await self._client.get_event(str(ranked[0][1].get("id") or ""))
        except EventNotFound:
            return None

    async def _candidates(self, query: str) -> list[dict[str, Any]]:
        page = await self._client.list_events(
            EventQuery(q=query, status="all", include_past=True, page_size=50)
        )
        if page["items"]:
            return [map_list_item(item) for item in page["items"]]

        found: list[dict[str, Any]] = []
        try:
            async for item in self._client.iter_all_events():
                found.append(map_list_item(item))
                if len(found) >= _FALLBACK_LIMIT:
                    break
        except ApiError:
            if not found:
                raise
        return found
