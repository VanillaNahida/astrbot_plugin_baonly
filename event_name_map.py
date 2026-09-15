import asyncio
import json
from pathlib import Path

from astrbot.api import logger
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

PLUGIN_NAME = "astrbot_plugin_baonly"

# 依 AstrBot 存储规范放在 data/plugin_data/{plugin_name}/ 下
_MAP_FILE = (
    Path(get_astrbot_data_path())
    / "plugin_data"
    / PLUGIN_NAME
    / "id_name_map.json"
)


class EventNameMap:
    """活动 id -> 活动名称的本地对照表，持久化到插件数据目录。"""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._map: dict[str, str] = {}
        self._loaded = False

    def _load_locked(self):
        if self._loaded:
            return
        self._loaded = True
        self._map = {}
        try:
            if _MAP_FILE.exists():
                data = json.loads(_MAP_FILE.read_text(encoding="utf-8"))
                mapping = data.get("map", {})
                if isinstance(mapping, dict):
                    self._map = {
                        str(k): str(v) for k, v in mapping.items() if v
                    }
        except Exception as e:
            logger.warning(f"[BAOnly] 读取 id->名称对照文件失败: {e}")

    def _save_locked(self):
        try:
            _MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
            _MAP_FILE.write_text(
                json.dumps({"map": self._map}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"[BAOnly] 写入 id->名称对照文件失败: {e}")

    async def update(self, event_id, name):
        event_id = str(event_id or "").strip()
        name = str(name or "").strip()
        if not event_id or not name:
            return
        async with self._lock:
            self._load_locked()
            if self._map.get(event_id) == name:
                return
            self._map[event_id] = name
            self._save_locked()
            logger.info(f"[BAOnly] 记录活动对照: {event_id} -> {name}")

    async def update_many(self, items):
        if not items:
            return
        async with self._lock:
            self._load_locked()
            changed = False
            for item in items:
                event_id = str(item.get("id") or "").strip()
                name = str(item.get("title") or "").strip()
                if event_id and name and self._map.get(event_id) != name:
                    self._map[event_id] = name
                    changed = True
            if changed:
                self._save_locked()
                logger.info(f"[BAOnly] 批量记录活动对照，当前共 {len(self._map)} 条")

    async def get(self, event_id):
        event_id = str(event_id or "").strip()
        if not event_id:
            return ""
        async with self._lock:
            self._load_locked()
            return self._map.get(event_id, "")

    @property
    def storage_path(self) -> str:
        return str(_MAP_FILE)


# 模块级默认实例，供各查询/推送路径共用
_default = EventNameMap()


async def record_event(event_id: str, title: str):
    await _default.update(event_id, title)


async def record_events(items):
    await _default.update_many(items)


async def event_name(event_id: str) -> str:
    return await _default.get(event_id)
