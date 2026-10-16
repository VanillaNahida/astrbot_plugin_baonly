from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from ...utils.jsonfile import read_json, write_json
from ...utils.log import log
from ...utils.text import clean
from ..meta import DATA_DIR
from .umo import build_umo, channel_of

STORE_FILE = DATA_DIR / "subscriptions.json"


@dataclass(frozen=True)
class Subscription:
    umo: str
    is_group: bool
    channel_id: str = ""
    display: str = ""

    @property
    def channel(self) -> str:
        return self.channel_id or channel_of(self.umo)

    @property
    def label(self) -> str:
        return self.display or self.umo

    @classmethod
    def create(cls, umo: str, is_group: bool, channel_id: str = "", display: str = "") -> Subscription:
        channel_id = clean(channel_id)
        return cls(build_umo(umo, is_group, channel_id), bool(is_group), channel_id, clean(display))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Subscription | None:
        if not clean(data.get("umo")):
            return None
        return cls.create(data["umo"], bool(data.get("is_group")), data.get("channel_id", ""), data.get("display", ""))


class SubscriptionStore:
    def __init__(self, path: Path = STORE_FILE):
        self._path = path
        self._lock = asyncio.Lock()
        self._items: list[Subscription] | None = None

    @property
    def storage_path(self) -> str:
        return str(self._path)

    async def list(self) -> list[Subscription]:
        async with self._lock:
            return list(self._loaded())

    async def add(self, subscription: Subscription) -> bool:
        async with self._lock:
            items = self._loaded()
            for index, existing in enumerate(items):
                if existing.umo == subscription.umo:
                    items[index] = replace(
                        existing,
                        is_group=subscription.is_group,
                        channel_id=subscription.channel_id or existing.channel_id,
                        display=subscription.display or existing.display,
                    )
                    self._save()
                    return False
            items.append(subscription)
            self._save()
            return True

    async def remove(self, umo: str) -> bool:
        async with self._lock:
            items = self._loaded()
            kept = [item for item in items if item.umo != umo]
            if len(kept) == len(items):
                return False
            self._items = kept
            self._save()
            return True

    def _loaded(self) -> list[Subscription]:
        if self._items is None:
            data = read_json(self._path)
            rows = data.get("subscriptions") if isinstance(data, dict) else None
            self._items = [
                sub for row in rows or [] if isinstance(row, dict) and (sub := Subscription.from_dict(row))
            ]
        return self._items

    def _save(self) -> None:
        try:
            write_json(self._path, {"subscriptions": [asdict(item) for item in self._items or []]})
        except OSError as exc:
            log.error(f"写入订阅文件失败: {exc}")
