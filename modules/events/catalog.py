from __future__ import annotations

import re
from typing import Any

from ..api import BaonlyClient, EventQuery
from ..api.mapping import map_detail, map_list_item
from ..api.search import EventSearch

_PLACE_SUFFIX = re.compile(r"(特别行政区|自治区|自治州|地区|省|市|区|县)$")


def _place_key(name: str) -> str:
    return _PLACE_SUFFIX.sub("", name.strip())


def _in_place(item: dict[str, Any], key: str) -> bool:
    city = item.get("city") if isinstance(item.get("city"), dict) else {}
    return any(key in str(city.get(field) or "") for field in ("name", "province"))


class EventCatalog:
    def __init__(self, client: BaonlyClient, default_page_size: int):
        self.client = client
        self.search = EventSearch(client)
        self.default_page_size = default_page_size

    def build_query(self, args: dict[str, Any]) -> EventQuery:
        return EventQuery.from_args(args, default_page_size=self.default_page_size)

    async def query(self, query: EventQuery) -> dict[str, Any]:
        data = await self.client.list_events(query)
        items = data["items"]
        if query.city and (key := _place_key(query.city)):
            items = [item for item in items if _in_place(item, key)]

        result: dict[str, Any] = {
            "total": data.get("total", 0),
            "page": data.get("page", query.page),
            "pageSize": data.get("pageSize", query.page_size),
            "pageCount": data.get("pageCount", 0),
            "query": query.describe(),
            "events_count": len(items),
            "events": [map_list_item(item) for item in items],
        }
        if query.facets is not None:
            result["facets"] = data.get("facets")
        return result

    async def detail(self, event_id: str) -> dict[str, Any]:
        return map_detail(await self.client.get_event(event_id))

    async def resolve(self, keyword: str) -> dict[str, Any] | None:
        return await self.search.resolve(keyword)
