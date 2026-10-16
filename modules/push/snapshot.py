from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from ...utils.text import clean
from ...utils.timefmt import format_time_range
from ..api.mapping import marker_labels
from ..events.groups import group_lines
from ..meta import EVENT_PAGE_URL
from .protocol import Action

Snapshot = dict[str, str]


@dataclass(frozen=True)
class DisplayField:
    label: str
    keys: tuple[str, ...]
    sources: tuple[str, ...]


DISPLAY_FIELDS = (
    DisplayField("标题", ("title",), ("title",)),
    DisplayField("时间", ("timeText",), ("startAt", "endAt", "timeLabel")),
    DisplayField("地点", ("province", "city"), ("city",)),
    DisplayField("场馆", ("venueName",), ("venue",)),
    DisplayField("票价", ("priceLabel",), ("priceLabel", "priceLowCents", "priceHighCents")),
    DisplayField("售票", ("saleFlag",), ("saleFlag",)),
    DisplayField("标记", ("markers",), ("markers",)),
    DisplayField("精选", ("featured",), ("featured",)),
)


def snapshot(detail: dict[str, Any]) -> Snapshot:
    start_at, end_at, time_label = detail.get("startAt"), detail.get("endAt"), detail.get("timeLabel")
    return {
        "title": clean(detail.get("title")),
        "startAt": clean(start_at),
        "endAt": clean(end_at),
        "timeLabel": clean(time_label),
        "timeText": format_time_range(start_at, end_at, time_label),
        "priceLabel": clean(detail.get("priceLabel")),
        "saleFlag": clean(detail.get("saleFlag")),
        "province": clean(detail.get("province")),
        "city": clean(detail.get("city")),
        "venueName": clean(detail.get("venueName")),
        "markers": marker_labels(detail.get("markers")),
        "featured": "1" if detail.get("featured") else "",
        "pcTicketUrl": clean(detail.get("pcTicketUrl")),
        "groups": "\n".join(group_lines(detail.get("infoItems"))),
    }


def displayed(server_fields: Iterable[str]) -> tuple[DisplayField, ...]:
    names = set(server_fields)
    return tuple(f for f in DISPLAY_FIELDS if names.intersection(f.sources))


def _time_text(snap: Snapshot) -> str:
    if text := clean(snap.get("timeText")):
        return text
    if not any(key in snap for key in ("startAt", "endAt", "timeLabel")):
        return ""
    return format_time_range(snap.get("startAt"), snap.get("endAt"), snap.get("timeLabel"))


def _value(snap: Snapshot, display: DisplayField) -> str:
    if display.keys == ("featured",):
        return "是" if snap.get("featured") else ""
    if display.keys == ("timeText",):
        return _time_text(snap)
    return "·".join(v for v in (clean(snap.get(k)) for k in display.keys) if v)


def diff(old: Snapshot, new: Snapshot) -> list[tuple[str, str, str]]:
    rows = []
    for display in DISPLAY_FIELDS:
        if any(key not in old for key in display.keys):
            continue
        before, after = _value(old, display), _value(new, display)
        if before != after:
            rows.append((display.label, before, after))
    return rows


def compose(
    event_id: str,
    action: Action,
    old: Snapshot | None = None,
    new: Snapshot | None = None,
    note: str = "",
    changed: Iterable[DisplayField] = (),
) -> str:
    old, new = old or {}, new or {}
    title = new.get("title") or old.get("title") or "（无标题）"
    lines = [f"[Baonly 活动{action.value}] {title}"]

    if action is Action.UPDATED:
        if old:
            for label, before, after in diff(old, new):
                lines += [f"--- {label}：{before or '（无）'}", f"+++ {label}：{after or '（无）'}"]
        else:
            lines += [f"+++ {d.label}：{_value(new, d) or '（无）'}" for d in changed if d.label != "标题"]
    else:
        source = old if action is Action.REMOVED else new
        lines += [
            f"{d.label}：{value}" for d in DISPLAY_FIELDS if d.label != "标题" and (value := _value(source, d))
        ]

    if groups := new.get("groups") or old.get("groups"):
        lines += groups.splitlines()
    if link := new.get("pcTicketUrl") or old.get("pcTicketUrl"):
        lines.append(f"购票链接：{link}")
    if note:
        lines.append(f"备注：{note}")
    if event_id:
        lines.append(f"详情页：{EVENT_PAGE_URL.format(event_id=event_id)}")
    return "\n".join(lines)
