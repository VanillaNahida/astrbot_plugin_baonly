from __future__ import annotations

from typing import Any

from ...utils.timefmt import format_time_range

MARKER_LABELS = {
    "cancelled": "已取消",
    "postponed": "已延期",
    "venueChanged": "地点变更",
}


def marker_labels(markers: Any) -> str:
    if not markers:
        return ""
    items = markers if isinstance(markers, (list, tuple)) else str(markers).split("、")
    return "、".join(MARKER_LABELS.get(str(m), str(m)) for m in items if m)


def _obj(item: dict[str, Any], key: str) -> dict[str, Any]:
    value = item.get(key)
    return value if isinstance(value, dict) else {}


def _list(item: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return [v for v in item.get(key) or [] if isinstance(v, dict)]


def _common(item: dict[str, Any]) -> dict[str, Any]:
    city = _obj(item, "city")
    venue = _obj(item, "venue")
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "timeText": format_time_range(item.get("startAt"), item.get("endAt"), item.get("timeLabel")),
        "timeLabel": item.get("timeLabel"),
        "startAt": item.get("startAt"),
        "endAt": item.get("endAt"),
        "state": item.get("status"),
        "priceLabel": item.get("priceLabel"),
        "priceLowCents": item.get("priceLowCents"),
        "priceHighCents": item.get("priceHighCents"),
        "saleFlag": item.get("saleFlag"),
        "wishCount": item.get("wishCount"),
        "highlightColor": item.get("highlightColor"),
        "featured": item.get("featured", False),
        "featuredMode": item.get("featuredMode"),
        "markers": item.get("markers") or [],
        "detailEnabled": item.get("detailEnabled", False),
        "distanceKm": item.get("distanceKm"),
        "province": city.get("province") or city.get("name"),
        "city": city.get("name"),
        "cityId": city.get("id"),
        "region": city.get("region"),
        "venueName": venue.get("name"),
        "address": venue.get("address"),
        "organizer": _obj(item, "organizer").get("name"),
    }


def map_list_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        **_common(item),
        "tags": [t.get("name") for t in _list(item, "tags")],
        "dates": [d.get("date") for d in _list(item, "dates")],
    }


def map_detail(item: dict[str, Any]) -> dict[str, Any]:
    return {
        **_common(item),
        "tags": [
            {
                "name": t.get("name"),
                "color": t.get("color"),
                "highlight": t.get("highlight"),
                "beforeTitle": t.get("beforeTitle"),
            }
            for t in _list(item, "tags")
        ],
        "description": item.get("description"),
        "coverUrl": _obj(item, "cover").get("url"),
        "bannerUrl": _obj(item, "banner").get("url"),
        "tickets": [
            {
                "name": t.get("name"),
                "screenName": t.get("screenName"),
                "priceCents": t.get("priceCents"),
                "priceLabel": t.get("priceLabel"),
                "saleFlag": t.get("saleFlag"),
                "saleStartAt": t.get("saleStartAt"),
                "saleEndAt": t.get("saleEndAt"),
            }
            for t in _list(item, "tickets")
        ],
        "guests": [
            {
                "name": g.get("name"),
                "description": g.get("description"),
                "imageUrl": _obj(g, "image").get("url"),
            }
            for g in _list(item, "guests")
        ],
        "infoItems": [
            {
                "id": i.get("id"),
                "section": i.get("section"),
                "title": i.get("title"),
                "content": i.get("content"),
            }
            for i in _list(item, "infoItems")
        ],
        "changeNotices": [
            {
                "field": n.get("field"),
                "oldValue": n.get("oldValue"),
                "newValue": n.get("newValue"),
                "noticedAt": n.get("noticedAt"),
            }
            for n in _list(item, "changeNotices")
        ],
        "detailImages": item.get("detailImages") or [],
        "pcTicketUrl": item.get("pcTicketUrl"),
        "mobileTicketUrl": item.get("mobileTicketUrl"),
    }
