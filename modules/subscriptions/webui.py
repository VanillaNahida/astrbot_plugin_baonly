from __future__ import annotations

from typing import Any

from astrbot.api.web import error_response, json_response, request

from ...utils.text import clean
from ..meta import PLUGIN_NAME
from .contacts import ContactDirectory
from .store import Subscription, SubscriptionStore
from .umo import FALLBACK_PLATFORM, message_type


class SubscriptionWebApi:
    def __init__(self, store: SubscriptionStore, contacts: ContactDirectory):
        self._store = store
        self._contacts = contacts

    def register(self, context: Any) -> None:
        routes = (
            ("list", self.list, "GET", "订阅渠道列表"),
            ("groups", self.groups, "GET", "可用群列表"),
            ("add", self.add, "POST", "新增订阅渠道"),
            ("remove", self.remove, "POST", "移除订阅渠道"),
        )
        for name, handler, method, desc in routes:
            context.register_web_api(f"/{PLUGIN_NAME}/subscriptions/{name}", handler, [method], desc)

    async def list(self):
        rows = [
            {
                "umo": sub.umo,
                "is_group": sub.is_group,
                "channel_id": sub.channel,
                "display": await self._contacts.display_name(sub.is_group, sub.channel, sub.display),
            }
            for sub in await self._store.list()
        ]
        return json_response({"total": len(rows), "subscriptions": rows, "storage_path": self._store.storage_path})

    async def groups(self):
        return json_response({"groups": await self._contacts.list_groups()})

    async def add(self):
        payload = await request.json(default={})
        channel_id = clean(payload.get("channel_id"))
        if not channel_id:
            return error_response("号码（群号或 QQ 号）不能为空", status_code=400)

        is_group = bool(payload.get("is_group"))
        platform = self._contacts.first_platform_id() or FALLBACK_PLATFORM
        umo = clean(payload.get("umo")) or f"{platform}:{message_type(is_group)}:{channel_id}"
        display = await self._contacts.display_name(is_group, channel_id, clean(payload.get("display")))

        subscription = Subscription.create(umo, is_group, channel_id, display)
        added = await self._store.add(subscription)
        return json_response(
            {
                "ok": True,
                "message": "订阅已添加" if added else "该渠道已订阅，信息已更新",
                "added": added,
                "umo": subscription.umo,
                "display": display,
            }
        )

    async def remove(self):
        payload = await request.json(default={})
        umo = clean(payload.get("umo"))
        if not umo:
            return error_response("会话唯一 ID(umo) 不能为空", status_code=400)
        removed = await self._store.remove(umo)
        return json_response({"ok": True, "message": "订阅已移除" if removed else "未找到该订阅", "removed": removed})
