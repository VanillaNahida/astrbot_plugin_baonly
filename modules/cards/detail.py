from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ...utils.text import clean, join_nonempty, yuan
from ...utils.timefmt import event_window, format_clock, format_time_range, now
from ..api.mapping import MARKER_LABELS
from ..meta import EVENT_PAGE_URL, SITE_ORIGIN, RuntimeInfo
from ..render import CardRenderer, render_template

_CLOSED_SALE_WORDS = ("售罄", "停售", "结束")
_INFO_SECTIONS = (("BASE_INFO", "基础信息", "info"), ("ORGANIZER", "主办信息", "badge-check"))
_MAP_SEARCH = (
    ("高德", "https://uri.amap.com/search?keyword={}"),
    ("百度", "https://map.baidu.com/search/{}"),
    ("腾讯", "https://map.qq.com/?type=marker&what={}"),
)


def _obj(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def _absolute(url: Any) -> str:
    url = clean(url)
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return SITE_ORIGIN + url
    return url


def _price(cents: Any, label: Any) -> str:
    return clean(label) or yuan(cents)


def countdown(start_at: Any, end_at: Any, status: Any, at: datetime | None = None) -> str:
    current = at or now()
    start, end = event_window(start_at, end_at)
    if status == "past" or (end and current > end):
        return "活动已结束"
    if start and end and start <= current <= end:
        return "正在进行中"
    if start is None:
        return ""

    remaining = int((start - current).total_seconds())
    if remaining <= 0:
        return "即将开始"
    days, rem = divmod(remaining, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    if days:
        return f"{days}天 {hours}小时 {minutes}分 {seconds}秒"
    if hours:
        return f"{hours}小时 {minutes}分 {seconds}秒"
    return f"{minutes}分 {seconds}秒"


@dataclass(frozen=True)
class MetaRow:
    icon: str
    main: str
    sub: str = ""
    links: tuple[dict[str, str], ...] = ()


@dataclass(frozen=True)
class DetailCard:
    title: str
    hero_urls: list[str]
    organizer: str
    organizer_badge: str
    countdown: str
    featured: bool
    markers: list[str]
    tags: list[str]
    meta_rows: list[MetaRow]
    description: str
    info_blocks: list[dict[str, Any]] = field(default_factory=list)
    tickets: list[dict[str, Any]] = field(default_factory=list)
    guests: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_api(cls, detail: dict[str, Any]) -> DetailCard:
        organizer = _obj(detail, "organizer")
        info_items = [i for i in detail.get("infoItems") or [] if isinstance(i, dict)]
        return cls(
            title=clean(detail.get("title")) or "未命名活动",
            hero_urls=[u for u in (_absolute(_obj(detail, k).get("url")) for k in ("cover", "banner")) if u],
            organizer=clean(organizer.get("name")),
            organizer_badge=clean(organizer.get("title")),
            countdown=countdown(detail.get("startAt"), detail.get("endAt"), detail.get("status")),
            featured=bool(detail.get("featured")),
            markers=[MARKER_LABELS.get(str(m), str(m)) for m in detail.get("markers") or []],
            tags=[t for t in (clean(t.get("name") if isinstance(t, dict) else t) for t in detail.get("tags") or []) if t],
            meta_rows=[_date_row(detail), _venue_row(detail), _price_row(detail)],
            description=clean(detail.get("description")),
            info_blocks=[
                {"title": title, "icon": icon, "rows": rows}
                for section, title, icon in _INFO_SECTIONS
                if (
                    rows := [
                        {"title": clean(i.get("title")), "content": clean(i.get("content"))}
                        for i in info_items
                        if i.get("section") == section
                    ]
                )
            ],
            tickets=[_ticket(t) for t in detail.get("tickets") or [] if isinstance(t, dict)],
            guests=[
                {
                    "avatar": _absolute(_obj(g, "image").get("url")),
                    "name": clean(g.get("name")),
                    "description": clean(g.get("description")),
                }
                for g in detail.get("guests") or []
                if isinstance(g, dict)
            ],
        )


def _date_row(detail: dict[str, Any]) -> MetaRow:
    text = format_time_range(detail.get("startAt"), detail.get("endAt"), detail.get("timeLabel"))
    return MetaRow("calendar", text)


def _venue_row(detail: dict[str, Any]) -> MetaRow:
    venue = _obj(detail, "venue")
    city = _obj(detail, "city")
    main = clean(venue.get("name")) or clean(city.get("name")) or "地点待定"
    sub = join_nonempty(city.get("province"), city.get("name"), venue.get("address"))
    keyword = clean(venue.get("address")) or clean(venue.get("name"))
    links = tuple(
        {"label": label, "url": template.format(quote(keyword))} for label, template in _MAP_SEARCH
    ) if keyword else ()
    return MetaRow("map-pin", main, "" if sub == main else sub, links)


def _price_row(detail: dict[str, Any]) -> MetaRow:
    low, high = detail.get("priceLowCents"), detail.get("priceHighCents")
    main = _price(low, detail.get("priceLabel")) or "票价待定"
    if low is not None and high and yuan(low) and yuan(high) and yuan(low) != yuan(high):
        main = f"{yuan(low)} - {yuan(high)}"
    sale = clean(detail.get("saleFlag"))
    if sale and detail.get("wishCount"):
        sale += f" · 想去 {detail['wishCount']}"
    return MetaRow("ticket", main, sale)


def _ticket(ticket: dict[str, Any]) -> dict[str, Any]:
    sale = clean(ticket.get("saleFlag"))
    return {
        "name": clean(ticket.get("name")) or "票档",
        "screen": clean(ticket.get("screenName")),
        "price": _price(ticket.get("priceCents"), ticket.get("priceLabel")) or "价格待定",
        "sale": sale,
        "sale_closed": any(word in sale for word in _CLOSED_SALE_WORDS),
    }


class DetailCardService:
    def __init__(self, renderer: CardRenderer, runtime: RuntimeInfo):
        self._renderer = renderer
        self._runtime = runtime

    def html(self, detail: dict[str, Any]) -> str:
        return render_template(
            "detail.html.j2",
            card=DetailCard.from_api(detail),
            footer_text=self._runtime.footer(format_clock()),
        )

    async def render(self, detail: dict[str, Any]) -> Path:
        return await self._renderer.render(self.html(detail), "baonly_detail_")

    @staticmethod
    def reply_chain(detail: dict[str, Any], image: Path) -> list[Any]:
        from astrbot.api.message_components import Image, Plain

        lines = []
        if title := clean(detail.get("title")):
            lines.append(f"【{title}】")
        if event_id := clean(detail.get("id")):
            lines.append(f"活动页面：{EVENT_PAGE_URL.format(event_id=event_id)}")
        if ticket_url := clean(detail.get("mobileTicketUrl")) or clean(detail.get("pcTicketUrl")):
            lines.append(f"购票链接：{ticket_url}")

        chain: list[Any] = [Plain("\n".join(lines))] if lines else []
        chain.append(Image.fromFileSystem(str(image)))
        return chain
