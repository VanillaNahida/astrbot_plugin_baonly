from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any


class Action(str, Enum):
    CREATED = "新增"
    UPDATED = "更新"
    REMOVED = "移除"


EVENT_ACTIONS = {
    "event.created": Action.CREATED,
    "event.updated": Action.UPDATED,
    "event.removed": Action.REMOVED,
}
BULK = "event.bulk"
READY = "ready"
CLOSING = "closing"
MAINTENANCE = "maintenance.changed"


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(v) for v in value if v)


@dataclass(frozen=True)
class StreamMessage:
    type: str
    raw: str
    seq: int | None = None
    event_ids: tuple[str, ...] = ()
    fields: tuple[str, ...] = ()
    note: str = ""
    scopes: tuple[str, ...] = ()
    code: int | None = None
    reason: str = ""
    enabled: bool | None = None

    @property
    def action(self) -> Action | None:
        return EVENT_ACTIONS.get(self.type)

    @property
    def is_event_change(self) -> bool:
        return (self.action is not None or self.type == BULK) and bool(self.event_ids)

    @property
    def preview(self) -> str:
        return self.raw[:200]


def parse(raw: str | bytes) -> StreamMessage | None:
    text = raw if isinstance(raw, str) else raw.decode("utf-8", errors="ignore")
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None

    single = data.get("eventId")
    seq = data.get("seq")
    code = data.get("code")
    enabled = data.get("enabled")
    return StreamMessage(
        type=str(data.get("type") or ""),
        raw=text,
        seq=seq if isinstance(seq, int) else None,
        event_ids=(str(single),) if single else _strings(data.get("eventIds")),
        fields=_strings(data.get("fields")),
        note=str(data.get("note") or "").strip(),
        scopes=_strings(data.get("scopes")),
        code=code if isinstance(code, int) else None,
        reason=str(data.get("reason") or "").strip(),
        enabled=enabled if isinstance(enabled, bool) else None,
    )
