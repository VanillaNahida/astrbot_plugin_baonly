import asyncio
import json
from pathlib import Path

from astrbot.api import logger
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

PLUGIN_NAME = "astrbot_plugin_baonly"

# 本插件目标平台会话统一标识：AstrBot:<GroupMessage|FriendMessage>:<群号/QQ号>
# 群聊用 GroupMessage，私聊用 FriendMessage。


def _normalize_umo(umo: str, is_group: bool, channel_id: str = "") -> str:
    token = "GroupMessage" if is_group else "FriendMessage"
    channel_id = str(channel_id or "").strip()
    if channel_id:
        # 有频道号时统一重建为严格目标格式
        return f"AstrBot:{token}:{channel_id}"
    # 无频道号时仅修正类型令牌大小写/旧值
    parts = str(umo).split(":")
    if len(parts) >= 3 and parts[1].lower() in (
        "group",
        "private",
        "groupmessage",
        "friendmessage",
    ):
        parts[1] = token
    return ":".join(parts)

# 订阅清单数据目录遵循 AstrBot 存储规范：data/plugin_data/{plugin_name}/
_SUBSCRIPTIONS_FILE = (
    Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME / "subscriptions.json"
)


class SubscriptionStore:
    """订阅渠道持久化存储。

    存 data/plugin_data/{plugin_name}/subscriptions.json，结构：
    {"subscriptions": [{"umo": "...", "is_group": bool, "channel_id": "...", "display": "..."}]}
    """

    def __init__(self):
        self._lock = asyncio.Lock()
        self._items = []
        self._loaded = False

    def _load_locked(self):
        if self._loaded:
            return
        self._loaded = True
        self._items = []
        try:
            if _SUBSCRIPTIONS_FILE.exists():
                data = json.loads(_SUBSCRIPTIONS_FILE.read_text(encoding="utf-8"))
                subs = data.get("subscriptions", [])
                if isinstance(subs, list):
                    for s in subs:
                        if isinstance(s, dict) and s.get("umo"):
                            is_group = bool(s.get("is_group", False))
                            umo = _normalize_umo(
                                s.get("umo"), is_group, s.get("channel_id", "")
                            )
                            self._items.append(
                                {
                                    "umo": umo,
                                    "is_group": is_group,
                                    "channel_id": s.get("channel_id", ""),
                                    "display": s.get("display", ""),
                                }
                            )
        except Exception as e:
            logger.warning(f"[BAOnly] 读取订阅文件失败: {e}")

    def _save_locked(self):
        try:
            _SUBSCRIPTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
            payload = {"subscriptions": self._items}
            _SUBSCRIPTIONS_FILE.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"[BAOnly] 写入订阅文件失败: {e}")

    async def list(self):
        async with self._lock:
            self._load_locked()
            return [dict(item) for item in self._items]

    async def has(self, umo: str) -> bool:
        async with self._lock:
            self._load_locked()
            return any(item["umo"] == umo for item in self._items)

    async def add(
        self, umo: str, is_group: bool, channel_id: str = "", display: str = ""
    ) -> bool:
        async with self._lock:
            self._load_locked()
            channel_id = str(channel_id or "").strip()
            umo = _normalize_umo(umo, bool(is_group), channel_id)
            for item in self._items:
                if item["umo"] == umo:
                    item["is_group"] = bool(is_group)
                    if channel_id:
                        item["channel_id"] = channel_id
                    if display:
                        item["display"] = display
                    return False
            self._items.append(
                {
                    "umo": umo,
                    "is_group": bool(is_group),
                    "channel_id": channel_id,
                    "display": display,
                }
            )
            self._save_locked()
            return True

    async def remove(self, umo: str) -> bool:
        async with self._lock:
            self._load_locked()
            new_items = [item for item in self._items if item["umo"] != umo]
            if len(new_items) == len(self._items):
                return False
            self._items = new_items
            self._save_locked()
            return True

    @property
    def storage_path(self) -> str:
        return str(_SUBSCRIPTIONS_FILE)
