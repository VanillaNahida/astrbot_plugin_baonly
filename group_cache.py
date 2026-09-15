from __future__ import annotations

import asyncio
import copy
import time
from typing import Any

from astrbot.api import logger


class GroupInfoCache:
    """从支持的平台(如 OneBot v11/aiocqhttp)获取群列表、群名与私聊昵称的缓存。

    用途：
    - 列出当前所有群（group_id + group_name + 所属平台名，用于 WebUI 快速订阅）
    - 根据群号反查群名，根据 QQ 号反查昵称（用于显示名）
    """

    def __init__(self, context, ttl_seconds: int = 120):
        self.context = context
        self.ttl_seconds = ttl_seconds

        self._lock = asyncio.Lock()
        self._last_refresh_at = 0.0
        self._group_list: list[dict[str, Any]] = []
        self._group_detail: dict[str, dict[str, Any]] = {}

    def _is_fresh(self) -> bool:
        return (time.time() - self._last_refresh_at) < self.ttl_seconds

    async def list_groups(self, force: bool = False) -> list[dict[str, Any]]:
        if force or not self._is_fresh() or not self._group_list:
            await self._refresh_group_list(force=force)
        return copy.deepcopy(self._group_list)

    async def get_group_name(self, group_id: str) -> str:
        normalized = str(group_id).strip()
        if not normalized:
            return ""
        if (
            not self._is_fresh()
            or normalized not in self._group_detail
        ):
            await self._refresh_group_list()
        detail = self._group_detail.get(normalized)
        if detail:
            return detail.get("group_name", "")
        return ""

    async def get_user_nickname(self, user_id: str) -> str:
        uid = str(user_id).strip()
        if not uid:
            return ""
        for client in self._iter_clients():
            try:
                result = await client.call_action("get_stranger_info", user_id=int(uid))
                info = self._extract_object(result)
                nickname = str(info.get("nickname", "")).strip()
                if nickname:
                    return nickname
            except Exception as exc:
                logger.debug("获取用户昵称失败 %s: %s", uid, exc)
        return ""

    async def first_platform_name(self) -> str:
        clients = self._iter_clients_with_platform()
        if not clients:
            return "aiocqhttp"
        return clients[0][1]

    def invalidate(self, group_id: str | None = None) -> None:
        if group_id:
            self._group_detail.pop(str(group_id).strip(), None)
            return
        self._group_detail.clear()
        self._last_refresh_at = 0.0

    async def _refresh_group_list(self, force: bool = False) -> None:
        async with self._lock:
            if not force and self._is_fresh() and self._group_list:
                return

            merged: dict[str, dict[str, Any]] = {}
            for client, platform_name in self._iter_clients_with_platform():
                try:
                    result = await client.call_action("get_group_list")
                    for item in self._extract_list(result):
                        group_id = str(item.get("group_id", "")).strip()
                        if not group_id or group_id in merged:
                            continue
                        merged[group_id] = {
                            "group_id": group_id,
                            "group_name": str(item.get("group_name", "")).strip()
                            or f"群 {group_id}",
                            "platform_name": platform_name,
                        }
                except Exception as exc:
                    logger.warning("获取群列表失败: %s", exc)

            self._group_list = list(merged.values())
            self._group_detail = merged
            self._last_refresh_at = time.time()

    def _iter_clients(self) -> list[Any]:
        return [c for c, _p in self._iter_clients_with_platform()]

    def _iter_clients_with_platform(self) -> list[tuple[Any, str]]:
        clients: list[tuple[Any, str]] = []
        try:
            from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_platform_adapter import (
                AiocqhttpAdapter,
            )
        except ImportError:
            return clients

        for inst in self.context.platform_manager.platform_insts:
            if not isinstance(inst, AiocqhttpAdapter):
                continue
            try:
                client = inst.get_client()
            except Exception:
                continue
            if client is not None:
                try:
                    platform_name = inst.meta().name
                except Exception:
                    platform_name = "aiocqhttp"
                clients.append((client, platform_name))
        return clients

    @staticmethod
    def _extract_list(result: Any) -> list[dict[str, Any]]:
        if isinstance(result, list):
            return [item for item in result if isinstance(item, dict)]
        if isinstance(result, dict):
            data = result.get("data")
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
        return []

    @staticmethod
    def _extract_object(result: Any) -> dict[str, Any]:
        if isinstance(result, dict):
            data = result.get("data")
            if isinstance(data, dict):
                return data
            return result
        return {}


def extract_channel_id(umo: str) -> str:
    """从 unified_msg_origin(形如 platform:type:id) 中提取会话 id。"""
    parts = str(umo).split(":")
    if len(parts) >= 3:
        return parts[-1]
    return umo
