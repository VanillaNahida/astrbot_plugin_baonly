from __future__ import annotations

from typing import Any

from ...utils.text import clean, join_nonempty
from ...utils.timefmt import format_time_range
from ..api.mapping import marker_labels

LIST_LIMIT = 10
TICKET_LIMIT = 6
DESCRIPTION_LIMIT = 200


def _time(event: dict[str, Any]) -> str:
    return format_time_range(event.get("startAt"), event.get("endAt"), event.get("timeLabel"), placeholder="待定")


def _price_line(event: dict[str, Any]) -> str:
    return f"  票价: {event.get('priceLabel') or '待定'} | 售票: {event.get('saleFlag') or '未知'}"


def format_event_list(result: dict[str, Any], status: str, city: str) -> str:
    scope = f"（查询: status={status}, city={city or '全部'}）"
    events = result.get("events") or []
    if not events:
        return f"暂无符合条件的活动{scope}。"

    blocks = [f"共 {result.get('events_count', 0)} 场相关活动{scope}："]
    for event in events[:LIST_LIMIT]:
        place = join_nonempty(event.get("province"), event.get("city"), sep=" ")
        lines = [
            f"- [{event.get('state')}] {event.get('title')}",
            f"  时间: {_time(event)}",
            f"  地点: {join_nonempty(place, event.get('venueName'), sep=' ')}",
            _price_line(event),
        ]
        if markers := marker_labels(event.get("markers")):
            lines.append(f"  标记: {markers}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def format_event_detail(detail: dict[str, Any]) -> str:
    lines = [f"- {detail.get('title')}"]
    if markers := marker_labels(detail.get("markers")):
        lines.append(f"  标记: {markers}")

    place = join_nonempty(detail.get("province"), detail.get("city"), detail.get("venueName"), sep=" ")
    lines += [
        f"  时间: {_time(detail)}",
        f"  地点: {join_nonempty(place or '待定', detail.get('address'), sep=' ')}",
        _price_line(detail),
    ]

    if tickets := detail.get("tickets") or []:
        lines.append("  票档:")
        lines += [
            f"    - {ticket.get('name') or '?'}：{ticket.get('priceLabel') or ticket.get('priceCents')}"
            for ticket in tickets[:TICKET_LIMIT]
        ]
    if description := clean(detail.get("description")):
        lines.append(f"  简介: {description[:DESCRIPTION_LIMIT]}")
    if ticket_url := clean(detail.get("pcTicketUrl")):
        lines.append(f"  购票: {ticket_url}")
    return "\n".join(lines)
