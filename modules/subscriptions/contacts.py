from __future__ import annotations

import asyncio
import time
from typing import Any

from ...utils.log import log
from ...utils.text import clean

GROUP_TTL_SECONDS = 120
NICKNAME_TTL_SECONDS = 1800
EMPTY_RETRY_SECONDS = 30


def _rows(result: Any) -> list[dict[str, Any]]:
    data = result.get("data") if isinstance(result, dict) else result
    return [row for row in data or [] if isinstance(row, dict)] if isinstance(data, list) else []


def _record(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    data = result.get("data")
    return data if isinstance(data, dict) else result


class ContactDirectory:
    def __init__(self, context: Any):
        self._context = context
        self._lock = asyncio.Lock()
        self._groups: dict[str, dict[str, str]] = {}
        self._groups_at = 0.0
        self._nicknames: dict[str, tuple[str, float]] = {}

    async def list_groups(self) -> list[dict[str, str]]:
        await self._refresh_groups()
        return [dict(group) for group in self._groups.values()]

    async def group_name(self, group_id: str) -> str:
        await self._refresh_groups()
        return self._groups.get(clean(group_id), {}).get("group_name", "")

    async def nickname(self, user_id: str) -> str:
        uid = clean(user_id)
        if not uid.isdigit():
            return ""
        cached = self._nicknames.get(uid)
        if cached and time.monotonic() - cached[1] < NICKNAME_TTL_SECONDS:
            return cached[0]
        for client, _ in self._clients():
            try:
                name = clean(_record(await client.call_action("get_stranger_info", user_id=int(uid))).get("nickname"))
            except Exception as exc:
                log.debug(f"获取用户昵称失败 {uid}: {exc}")
                continue
            if name:
                self._nicknames[uid] = (name, time.monotonic())
                return name
        return ""

    async def display_name(self, is_group: bool, channel_id: str, fallback: str = "") -> str:
        if not channel_id:
            return fallback
        name = await (self.group_name(channel_id) if is_group else self.nickname(channel_id))
        return name or fallback

    def first_platform_id(self) -> str:
        for adapter in self._adapters():
            try:
                if platform_id := clean(adapter.meta().id):
                    return platform_id
            except Exception:
                continue
        return ""

    async def _refresh_groups(self) -> None:
        async with self._lock:
            ttl = GROUP_TTL_SECONDS if self._groups else EMPTY_RETRY_SECONDS
            if time.monotonic() - self._groups_at < ttl:
                return
            merged: dict[str, dict[str, str]] = {}
            for client, platform_name in self._clients():
                try:
                    rows = _rows(await client.call_action("get_group_list"))
                except Exception as exc:
                    log.warning(f"获取群列表失败: {exc}")
                    continue
                for row in rows:
                    group_id = clean(row.get("group_id"))
                    if group_id and group_id not in merged:
                        merged[group_id] = {
                            "group_id": group_id,
                            "group_name": clean(row.get("group_name")) or f"群 {group_id}",
                            "platform_name": platform_name,
                        }
            self._groups = merged
            self._groups_at = time.monotonic()

    def _adapters(self) -> list[Any]:
        try:
            from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_platform_adapter import AiocqhttpAdapter
        except ImportError:
            return []
        return [inst for inst in self._context.platform_manager.platform_insts if isinstance(inst, AiocqhttpAdapter)]

    def _clients(self) -> list[tuple[Any, str]]:
        clients = []
        for adapter in self._adapters():
            try:
                client = adapter.get_client()
                name = adapter.meta().name
            except Exception:
                continue
            if client is not None:
                clients.append((client, name or "aiocqhttp"))
        return clients
