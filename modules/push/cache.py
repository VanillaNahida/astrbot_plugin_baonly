from __future__ import annotations

from pathlib import Path

from ...utils.jsonfile import read_json, write_json
from ...utils.log import log
from ...utils.timefmt import now
from ..meta import DATA_DIR
from .snapshot import Snapshot

CACHE_FILE = DATA_DIR / "activities_cache.json"


class SnapshotCache:
    def __init__(self, path: Path = CACHE_FILE):
        self._path = path

    def load(self) -> dict[str, Snapshot] | None:
        data = read_json(self._path)
        events = data.get("events") if isinstance(data, dict) else None
        if not isinstance(events, dict):
            return None
        return {str(k): v for k, v in events.items() if isinstance(v, dict)}

    def save(self, events: dict[str, Snapshot]) -> None:
        try:
            write_json(self._path, {"updatedAt": now().strftime("%Y-%m-%d %H:%M:%S"), "events": events})
        except OSError as exc:
            log.error(f"写入活动缓存失败: {exc}")
