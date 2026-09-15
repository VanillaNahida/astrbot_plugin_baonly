from .group_cache import GroupInfoCache, extract_channel_id
from .subscriptions import SubscriptionStore


async def _resolve_display(group_cache, is_group: bool, channel_id: str, fallback: str) -> str:
    """按号码解析显示名：群→群昵称，私聊→用户昵称。"""
    if not channel_id:
        return fallback
    if is_group:
        name = await group_cache.get_group_name(channel_id)
        return name or fallback
    nickname = await group_cache.get_user_nickname(channel_id)
    return nickname or fallback


class SubscriptionPageService:
    """Page 后端业务：管理订阅渠道（按号码解析显示名）。"""

    def __init__(self, store: SubscriptionStore, group_cache: GroupInfoCache):
        self._store = store
        self._group_cache = group_cache

    async def list_subscriptions(self):
        subs = await self._store.list()
        resolved = []
        for s in subs:
            is_group = bool(s.get("is_group", False))
            channel_id = s.get("channel_id", "") or extract_channel_id(s.get("umo", ""))
            display = await _resolve_display(
                self._group_cache, is_group, channel_id, s.get("display", "")
            )
            resolved.append(
                {
                    "umo": s.get("umo"),
                    "is_group": is_group,
                    "channel_id": channel_id,
                    "display": display,
                }
            )
        return {
            "total": len(resolved),
            "subscriptions": resolved,
            "storage_path": self._store.storage_path,
        }

    async def list_available_groups(self):
        return await self._group_cache.list_groups()

    async def add_subscription(self, umo="", is_group=False, channel_id="", display=""):
        channel_id = (channel_id or "").strip()
        if not channel_id:
            return {"ok": False, "message": "号码（群号或 QQ 号）不能为空"}
        umo = (umo or "").strip()
        if not umo:
            # 无 umo 时按固定格式拼装：AstrBot:GroupMessage:<群号>（私聊为 FriendMessage）
            # 这是本插件订阅推送目标平台的统一会话标识。
            msg_type = "GroupMessage" if is_group else "FriendMessage"
            umo = f"AstrBot:{msg_type}:{channel_id}"
        resolved_display = await _resolve_display(
            self._group_cache, bool(is_group), channel_id, display
        )
        is_new = await self._store.add(
            umo, bool(is_group), channel_id, resolved_display
        )
        return {
            "ok": True,
            "message": "订阅已添加" if is_new else "该渠道已订阅，信息已更新",
            "added": is_new,
            "umo": umo,
            "display": resolved_display,
        }

    async def remove_subscription(self, umo):
        umo = (umo or "").strip()
        if not umo:
            return {"ok": False, "message": "会话唯一 ID(umo) 不能为空"}
        removed = await self._store.remove(umo)
        return {
            "ok": True,
            "message": "订阅已移除" if removed else "未找到该订阅",
            "removed": removed,
        }
