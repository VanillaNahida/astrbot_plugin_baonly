from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

import httpx

from ...utils.log import log
from ..meta import API_BASE
from .errors import ApiError, EventNotFound
from .query import EventQuery

_EVENT_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def is_event_id(value: str) -> bool:
    return bool(_EVENT_ID.match((value or "").strip()))


class BaonlyClient:
    def __init__(self, token: str, user_agent: str, timeout: float = 30.0):
        self._headers = {"User-Agent": user_agent, "x-api-key": token}
        self._timeout = timeout
        self._http: httpx.AsyncClient | None = None

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def list_events(self, query: EventQuery) -> dict[str, Any]:
        data = await self._get_json("/events", params=query.to_params())
        data["items"] = [item for item in data.get("items") or [] if isinstance(item, dict)]
        return data

    async def get_event(self, event_id: str) -> dict[str, Any]:
        event_id = (event_id or "").strip()
        if not is_event_id(event_id):
            raise EventNotFound(event_id)
        return await self._get_json(f"/events/{quote(event_id, safe='')}", not_found=event_id)

    async def iter_all_events(self, page_size: int = 200) -> AsyncIterator[dict[str, Any]]:
        page = 1
        while True:
            data = await self.list_events(
                EventQuery(status="all", include_past=True, page=page, page_size=page_size)
            )
            for item in data["items"]:
                yield item
            page_count = int(data.get("pageCount") or 0)
            if not data["items"] or page >= page_count:
                return
            page += 1

    async def _get_json(
        self, path: str, *, params: dict[str, str] | None = None, not_found: str | None = None
    ) -> dict[str, Any]:
        url = API_BASE + path
        log.debug(f"GET {url} {params or ''}")
        try:
            resp = await self._client().get(url, params=params)
        except httpx.RequestError as exc:
            log.warning(f"网络请求失败 {url}: {exc!r}")
            raise ApiError(f"网络请求失败: {exc}") from exc

        if resp.status_code == 404 and not_found is not None:
            raise EventNotFound(not_found)
        if resp.is_error:
            log.warning(f"API 请求失败 {url}: {resp.status_code} {resp.text[:200]}")
            raise ApiError(f"API 请求失败，状态码: {resp.status_code}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise ApiError("API 返回了非 JSON 内容，站点可能在维护中") from exc
        if not isinstance(data, dict):
            raise ApiError("API 返回格式异常")
        return data

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(headers=self._headers, timeout=self._timeout)
        return self._http
