"""BAOnly 展会详情卡片：HTML 模板构建 + 双后端渲染。

图标为 Lucide 内联 SVG（ISC License），currentColor 着色，无 emoji、无字体依赖。
渲染后端：
- ``astrbot``：AstrBot 自带 html_render（远端 t2i 端点）
- ``playwright``：本地 Playwright 渲染（插件已依赖）
- ``auto``：优先 astrbot，失败回退 playwright
"""

import html as _html
import os
import re
import shutil
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote as _urlquote

from astrbot.api import logger

PLUGIN_NAME = "astrbot_plugin_baonly"
CARD_WIDTH = 414

# 接口返回的图片是站内相对路径（如 /images/xx/yy/zz.webp），需要补全为绝对 URL
BAONLY_ORIGIN = "https://beta.baonly.cn"

# 活动详情页地址
BAONLY_EVENT_URL = BAONLY_ORIGIN + "/event/{event_id}"

# 全局字体 Blueaka（常规 400 / 加粗 700 均为同一 font-family，靠字重区分）。
# 注意：这里必须写全 https://，因为本地渲染走 set_content，页面基址是 about:blank，
# 协议相对地址（//cdn...）无法解析。
_FONT_LINKS = (
    '<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/VanillaNahida/'
    'BA-Spark-Cursor/fonts/Blueaka/Blueaka.css">'
    '<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/VanillaNahida/'
    'BA-Spark-Cursor/fonts/Blueaka_Bold/Blueaka_Bold.css">'
)

# 可选的渲染后端
VALID_RENDER_MODES = ("auto", "astrbot", "playwright")


def render_options_from_config(config) -> dict:
    """从插件配置提取渲染参数（后端 / UA / 代理），供命令与 LLM 工具共用。"""
    config = config or {}
    mode = str(config.get("detail_render_mode", "auto") or "auto").lower()
    if mode not in VALID_RENDER_MODES:
        mode = "auto"
    return {
        "mode": mode,
        "user_agent": config.get("user_agent", "") or "",
        "proxy_host": config.get("proxy_host", "") or "",
        "proxy_port": config.get("proxy_port", "") or "",
        "proxy_username": config.get("proxy_username", "") or "",
        "proxy_password": config.get("proxy_password", "") or "",
    }

# --------------------------------------------------------------------------
# 图标：Lucide (ISC License) 内联 SVG
# --------------------------------------------------------------------------

_RAW_ICONS = {
    "calendar": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 2v3"/><path d="M16 2v3"/><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18"/><path d="M8 13h.01"/><path d="M12 13h.01"/><path d="M16 13h.01"/><path d="M8 17h.01"/><path d="M12 17h.01"/><path d="M16 17h.01"/></svg>',
    "clock": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>',
    "map-pin": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 10c0 4.993-5.539 10.193-7.399 11.799a1 1 0 0 1-1.202 0C9.539 20.193 4 14.993 4 10a8 8 0 0 1 16 0"/><circle cx="12" cy="10" r="3"/></svg>',
    "navigation": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="3 11 22 2 13 21 11 13 3 11"/></svg>',
    "ticket": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 9a3 3 0 0 1 0 6v2a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-2a3 3 0 0 1 0-6V7a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2Z"/><path d="M13 5v2"/><path d="M13 17v2"/><path d="M13 11v2"/></svg>',
    "users": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><path d="M16 3.128a4 4 0 0 1 0 7.744"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><circle cx="9" cy="7" r="4"/></svg>',
    "badge-check": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3.85 8.62a4 4 0 0 1 4.78-4.77 4 4 0 0 1 6.74 0 4 4 0 0 1 4.78 4.78 4 4 0 0 1 0 6.74 4 4 0 0 1-4.77 4.78 4 4 0 0 1-6.75 0 4 4 0 0 1-4.78-4.77 4 4 0 0 1 0-6.76Z"/><path d="m16 9-5.5 5.5L8 12"/></svg>',
    "sparkles": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11.017 2.814a1 1 0 0 1 1.966 0l1.051 5.558a2 2 0 0 0 1.594 1.594l5.558 1.051a1 1 0 0 1 0 1.966l-5.558 1.051a2 2 0 0 0-1.594 1.594l-1.051 5.558a1 1 0 0 1-1.966 0l-1.051-5.558a2 2 0 0 0-1.594-1.594l-5.558-1.051a1 1 0 0 1 0-1.966l5.558-1.051a2 2 0 0 0 1.594-1.594z"/><path d="M20 2v4"/><path d="M22 4h-4"/><circle cx="4" cy="20" r="2"/></svg>',
    "triangle-alert": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>',
    "info": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>',
    "file-text": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"/><path d="M14 2v5a1 1 0 0 0 1 1h5"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/></svg>',
    "images": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m22 11-1.296-1.296a2.4 2.4 0 0 0-3.408 0L11 16"/><path d="M4 8a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2"/><circle cx="13" cy="7" r="1" fill="currentColor"/><rect x="8" y="2" rx="2"/></svg>',
}


def _icon(name: str, size: int = 20) -> str:
    """返回指定尺寸的内联 SVG 图标（Lucide）。"""
    svg = _RAW_ICONS.get(name)
    if not svg:
        return ""
    return svg.replace(
        "<svg ", f'<svg width="{size}" height="{size}" aria-hidden="true" ', 1
    )


# --------------------------------------------------------------------------
# 通用工具
# --------------------------------------------------------------------------


def _esc(value) -> str:
    """HTML 转义，None 视为空串。"""
    if value is None:
        return ""
    return _html.escape(str(value), quote=True)


def _text(value) -> str:
    """取纯文本（去首尾空白）。"""
    if value is None:
        return ""
    return str(value).strip()


def _join(*parts) -> str:
    """用 · 连接非空片段。"""
    return " · ".join(p for p in (str(x).strip() for x in parts) if p)


def _abs_url(value) -> str:
    """把接口返回的相对图片路径补全为绝对 URL。"""
    url = _text(value)
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return BAONLY_ORIGIN + url
    return url


_CST = timezone(timedelta(hours=8))


def _parse_dt(value):
    """解析 ISO 8601 时间串并归一到东八区，失败返回 None。"""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_CST)
    return dt.astimezone(_CST)


def _countdown_text(start_at, end_at, status) -> str:
    """生成倒计时/状态文案。"""
    now = datetime.now(_CST)
    start = _parse_dt(start_at)
    end = _parse_dt(end_at) or start

    if start and end and start <= now <= end:
        return "正在进行中"
    if status == "past" or (end and now > end):
        return "活动已结束"
    if not start:
        return ""

    delta = int((start - now).total_seconds())
    if delta <= 0:
        return "即将开始"
    days, rem = divmod(delta, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    if days:
        return f"{days}天 {hours}小时 {minutes}分 {seconds}秒"
    if hours:
        return f"{hours}小时 {minutes}分 {seconds}秒"
    return f"{minutes}分 {seconds}秒"


def _money(cents, fallback_label) -> str:
    """价格展示：优先原始文案，其次由分换算。"""
    label = _text(fallback_label)
    if label:
        return label
    if cents is None:
        return ""
    try:
        yuan = float(cents) / 100
    except (TypeError, ValueError):
        return ""
    return f"{yuan:g}元"


def _sale_class(flag: str) -> str:
    """售票状态配色：售罄/停售为灰，其余为品牌粉。"""
    if any(k in flag for k in ("售罄", "停售", "结束")):
        return "ticket-sale ticket-sale-off"
    return "ticket-sale"


_MARKER_LABELS = {
    "cancelled": "已取消",
    "postponed": "已延期",
    "venueChanged": "地点变更",
}


# --------------------------------------------------------------------------
# 卡片片段
# --------------------------------------------------------------------------


def _hero(detail: dict) -> str:
    """顶部主视觉：优先竖版封面，回退横版头图。"""
    cover = (detail.get("cover") or {}).get("url")
    banner = (detail.get("banner") or {}).get("url")
    url = _abs_url(cover) or _abs_url(banner)
    if url:
        return (
            '<div class="hero"><img src="{}" alt=""></div>'.format(_esc(url))
        )
    return (
        '<div class="hero"><div class="hero-empty">{}</div></div>'.format(
            _icon("images", 44)
        )
    )


def _org_row(detail: dict) -> str:
    org = detail.get("organizer") or {}
    name = _text(org.get("name"))
    badge = _text(org.get("title"))
    if not name and not badge:
        return ""
    badge_html = ""
    if badge:
        badge_html = '<span class="verified">{}<span>{}</span></span>'.format(
            _icon("badge-check", 14), _esc(badge)
        )
    return '<div class="org"><span class="org-name">{}</span>{}</div>'.format(
        _esc(name), badge_html
    )


def _chips(detail: dict) -> str:
    """标签行：精选 / 运营标记 / 活动标签。"""
    chips = []
    if detail.get("featured"):
        chips.append(
            '<span class="chip chip-featured">{}<span>精选</span></span>'.format(
                _icon("sparkles", 13)
            )
        )
    for marker in detail.get("markers") or []:
        label = _MARKER_LABELS.get(str(marker), str(marker))
        chips.append(
            '<span class="chip chip-marker">{}<span>{}</span></span>'.format(
                _icon("triangle-alert", 13), _esc(label)
            )
        )
    for tag in detail.get("tags") or []:
        name = _text(tag.get("name")) if isinstance(tag, dict) else _text(tag)
        if name:
            chips.append(
                '<span class="chip chip-tag">{}</span>'.format(_esc(name))
            )
    if not chips:
        return ""
    return '<div class="chips">{}</div>'.format("".join(chips))


def _map_links(detail: dict) -> str:
    """地图跳转链接（渲染为图片时仅作展示）。"""
    venue = detail.get("venue") or {}
    keyword = _text(venue.get("address")) or _text(venue.get("name"))
    if not keyword:
        return ""
    kw = _urlquote(keyword)
    targets = [
        ("高德", f"https://uri.amap.com/search?keyword={kw}"),
        ("百度", f"https://map.baidu.com/search/{kw}"),
        ("腾讯", f"https://map.qq.com/?type=marker&what={kw}"),
    ]
    links = "".join(
        '<a class="maplink" href="{}">{}<span>{}</span></a>'.format(
            _esc(url), _icon("navigation", 11), label
        )
        for label, url in targets
    )
    return f'<div class="maplinks">{links}</div>'


def _meta_rows(detail: dict) -> str:
    """日期 / 地点 / 票价 三行信息。"""
    rows = []

    date_main = _text(detail.get("timeLabel"))
    start = _parse_dt(detail.get("startAt"))
    end = _parse_dt(detail.get("endAt"))
    if not date_main and start:
        date_main = start.strftime("%Y年%m月%d日")
    date_sub = ""
    if start:
        date_sub = start.strftime("%Y.%m.%d")
        if end and end.date() != start.date():
            date_sub += end.strftime(" - %Y.%m.%d")
    # timeLabel 有时本身就是日期文案，避免主副标题重复
    if date_sub and re.sub(r"\D", "", date_sub) == re.sub(r"\D", "", date_main):
        date_sub = ""
    if date_main or date_sub:
        rows.append(
            _meta_row("calendar", date_main or "时间待定", date_sub)
        )

    venue = detail.get("venue") or {}
    city = detail.get("city") or {}
    venue_main = _text(venue.get("name")) or _text(city.get("name")) or "地点待定"
    venue_sub = _join(city.get("province"), city.get("name"), venue.get("address"))
    if venue_sub == venue_main:
        venue_sub = ""
    rows.append(
        _meta_row("map-pin", venue_main, venue_sub, _map_links(detail))
    )

    price_main = _join(
        _money(detail.get("priceLowCents"), detail.get("priceLabel")),
        None,
    )
    if not price_main:
        price_main = "票价待定"
    if detail.get("priceLowCents") is not None and detail.get("priceHighCents"):
        low = _money(detail.get("priceLowCents"), None)
        high = _money(detail.get("priceHighCents"), None)
        if low and high and low != high:
            price_main = f"{low} - {high}"
    sale = _text(detail.get("saleFlag"))
    if sale:
        sale += f" · 想去 {detail['wishCount']}" if detail.get("wishCount") else ""
    rows.append(_meta_row("ticket", price_main, sale))

    return '<div class="meta">{}</div>'.format("".join(rows))


def _meta_row(icon_name: str, main: str, sub: str = "", extra: str = "") -> str:
    sub_html = f'<div class="meta-sub">{_esc(sub)}</div>' if sub else ""
    return (
        '<div class="meta-row">'
        '<div class="meta-ic">{icon}</div>'
        "<div><div class=\"meta-main\">{main}</div>{sub}{extra}</div>"
        "</div>"
    ).format(
        icon=_icon(icon_name, 20),
        main=_esc(main),
        sub=sub_html,
        extra=extra,
    )


def _description_section(detail: dict) -> str:
    """活动详情（简介正文），保留原文换行与段落。"""
    text = _text(detail.get("description"))
    if not text:
        return ""
    return (
        '<div class="section"><h2><span class="hic">{icon}</span>活动详情</h2>'
        '<div class="desc">{text}</div></div>'
    ).format(icon=_icon("file-text", 18), text=_esc(text))


def _kv_section(title: str, icon_name: str, items: list) -> str:
    if not items:
        return ""
    rows = "".join(
        '<div class="kv"><div class="k">{}</div><div class="v">{}</div></div>'.format(
            _esc(item.get("title")), _esc(item.get("content"))
        )
        for item in items
    )
    return (
        '<div class="section"><h2><span class="hic">{icon}</span>{title}</h2>'
        '<div class="kv-list">{rows}</div></div>'
    ).format(icon=_icon(icon_name, 18), title=_esc(title), rows=rows)


def _tickets_section(detail: dict) -> str:
    tickets = detail.get("tickets") or []
    if not tickets:
        return ""
    cards = []
    for t in tickets:
        price = _money(t.get("priceCents"), t.get("priceLabel")) or "价格待定"
        sale = _text(t.get("saleFlag"))
        cards.append(
            '<div class="ticket">'
            '<div><div class="ticket-name">{name}</div>'
            '<div class="ticket-sub">{sub}</div></div>'
            '<div class="ticket-right"><div class="ticket-price">{price}</div>'
            '<div class="{cls}">{sale}</div></div>'
            "</div>".format(
                name=_esc(_text(t.get("name")) or "票档"),
                sub=_esc(_text(t.get("screenName"))),
                price=_esc(price),
                cls=_sale_class(sale),
                sale=_esc(sale),
            )
        )
    return (
        '<div class="section"><h2><span class="hic">{icon}</span>票务</h2>'
        "{cards}</div>"
    ).format(icon=_icon("ticket", 18), cards="".join(cards))


def _guests_section(detail: dict) -> str:
    guests = detail.get("guests") or []
    if not guests:
        return ""
    cards = []
    for g in guests:
        avatar = _abs_url((g.get("image") or {}).get("url"))
        if avatar:
            media = '<img src="{}" alt="">'.format(_esc(avatar))
        else:
            media = '<div class="guest-ph">{}</div>'.format(_icon("users", 26))
        cards.append(
            '<div class="guest">{media}'
            '<div class="guest-name">{name}</div>'
            '<div class="guest-desc">{desc}</div></div>'.format(
                media=media,
                name=_esc(_text(g.get("name"))),
                desc=_esc(_text(g.get("description"))),
            )
        )
    return (
        '<div class="section"><h2><span class="hic">{icon}</span>嘉宾</h2>'
        '<div class="guests">{cards}</div></div>'
    ).format(icon=_icon("users", 18), cards="".join(cards))


_CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: #FFFFFF;
  color: #333333;
  font-family: "Blueaka", -apple-system, BlinkMacSystemFont, "Helvetica Neue",
    "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
}
.card { width: __WIDTH__px; margin: 0 auto; background: #FFFFFF; }
.hero { width: 100%; aspect-ratio: 3 / 4; background: #EFEFEF; overflow: hidden; }
.hero img { width: 100%; height: 100%; object-fit: cover; display: block; }
.hero-empty {
  width: 100%; height: 100%; display: flex; align-items: center; justify-content: center;
  color: #C4C4C4; background: linear-gradient(135deg, #F2F2F2, #E4E4E4);
}
.body {
  position: relative; z-index: 2; margin-top: -20px;
  background: #FFFFFF; border-radius: 16px 16px 0 0; padding: 16px 16px 28px;
}
h1 { font-size: 22px; line-height: 1.35; font-weight: 700; margin-bottom: 10px; }
.org { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.org-name { font-size: 14px; color: #666666; }
.verified {
  display: inline-flex; align-items: center; gap: 4px; font-size: 12px;
  background: #E8F5E9; color: #4CAF50; padding: 2px 8px 2px 6px; border-radius: 4px;
}
.countdown { color: #E94E99; font-size: 14px; font-weight: 700; margin-bottom: 12px; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; }
.chip {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 12px; padding: 4px 10px; border-radius: 12px;
}
.chip-featured { background: #FFF3E0; color: #F57C00; }
.chip-tag { background: #FCE4EC; color: #E94E99; }
.chip-marker { background: #FFEBEE; color: #D32F2F; }
.meta { display: flex; flex-direction: column; gap: 12px; margin-bottom: 18px; }
.meta-row { display: flex; align-items: flex-start; gap: 12px; }
.meta-ic { flex: 0 0 20px; height: 20px; color: #BDBDBD; }
.meta-main { font-size: 14px; color: #333333; line-height: 1.5; }
.meta-sub { font-size: 12px; color: #888888; margin-top: 2px; line-height: 1.5; }
.maplinks { display: flex; gap: 6px; margin-top: 6px; }
.maplink {
  display: inline-flex; align-items: center; gap: 3px; font-size: 11px;
  color: #E94E99; border: 1px solid #F8BBD0; border-radius: 10px;
  padding: 1px 7px; text-decoration: none;
}
.section { margin-bottom: 26px; }
.section h2 {
  display: flex; align-items: center; gap: 6px;
  font-size: 16px; font-weight: 700; margin-bottom: 12px;
}
.hic { display: flex; color: #E94E99; }
.kv-list { display: flex; flex-direction: column; }
.kv { display: flex; font-size: 13px; padding: 5px 0; }
.kv .k { flex: 0 0 80px; width: 80px; color: #888888; }
.kv .v { flex: 1; color: #333333; line-height: 1.6; }
.desc {
  font-size: 13px; color: #333333; line-height: 1.75;
  white-space: pre-wrap; word-break: break-word;
}
.footer {
  text-align: center; padding: 12px 0 0; margin-top: 20px;
  border-top: 1px solid #EEEEEE;
  font-size: 11px; color: #999999; line-height: 1.6;
}
.ticket {
  display: flex; justify-content: space-between; align-items: center;
  border: 1px solid #E0E0E0; border-radius: 12px; padding: 12px 16px; margin-bottom: 10px;
}
.ticket-name { font-size: 14px; font-weight: 500; color: #333333; }
.ticket-sub { font-size: 12px; color: #888888; margin-top: 4px; }
.ticket-right { text-align: right; }
.ticket-price { font-size: 14px; color: #333333; }
.ticket-sale { font-size: 12px; color: #E94E99; margin-top: 4px; }
.ticket-sale-off { color: #888888; }
.guests { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.guest { text-align: center; }
.guest img, .guest-ph {
  width: 100%; aspect-ratio: 1; border-radius: 12px; object-fit: cover;
  display: block; margin-bottom: 6px; background: #F2F2F2;
}
.guest-ph {
  display: flex; align-items: center; justify-content: center; color: #C4C4C4;
}
.guest-name { font-size: 13px; font-weight: 700; color: #333333; }
.guest-desc {
  font-size: 11px; color: #888888; margin-top: 2px; line-height: 1.45;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden;
}
""".replace("__WIDTH__", str(CARD_WIDTH))


def _footer_html(
    astrbot_version: str = "",
    plugin_name: str = "",
    plugin_version: str = "",
) -> str:
    """详情卡片页脚：复用网页截图的版本信息文案，保证两类图片一致。"""
    from importlib.metadata import version as _pkg_version

    from .baonly_screenshot import build_footer_text

    try:
        playwright_ver = _pkg_version("playwright")
    except Exception:
        playwright_ver = ""

    text = build_footer_text(
        playwright_ver,
        datetime.now().strftime("%Y/%m/%d %H:%M"),
        astrbot_version,
        plugin_name,
        plugin_version,
    )
    return '<div class="footer">{}</div>'.format(_esc(text))


def build_detail_card_html(
    detail: dict,
    astrbot_version: str = "",
    plugin_name: str = "",
    plugin_version: str = "",
) -> str:
    """把活动详情（PublicEventDetailDto 原始结构）渲染为完整 HTML 字符串。"""
    detail = detail or {}
    info_items = detail.get("infoItems") or []
    base_items = [i for i in info_items if i.get("section") == "BASE_INFO"]
    organizer_items = [i for i in info_items if i.get("section") == "ORGANIZER"]

    title = _text(detail.get("title")) or "未命名活动"
    countdown = _countdown_text(
        detail.get("startAt"), detail.get("endAt"), detail.get("status")
    )
    countdown_html = (
        '<div class="countdown">{}{}</div>'.format(
            _icon("clock", 14), _esc(countdown)
        )
        if countdown
        else ""
    )

    body = "".join(
        [
            f"<h1>{_esc(title)}</h1>",
            _org_row(detail),
            countdown_html,
            _chips(detail),
            _meta_rows(detail),
            _description_section(detail),
            _kv_section("基础信息", "info", base_items),
            _kv_section("主办信息", "badge-check", organizer_items),
            _tickets_section(detail),
            _guests_section(detail),
            _footer_html(astrbot_version, plugin_name, plugin_version),
        ]
    )

    return (
        "<!DOCTYPE html>"
        '<html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"{_FONT_LINKS}"
        f"<style>{_CSS}</style></head><body>"
        f'<div class="card">{_hero(detail)}<div class="body">{body}</div></div>'
        "</body></html>"
    )


def build_detail_reply_chain(detail: dict, image_path: str) -> list:
    """构造「标题 + 活动页面链接 + 购票链接 + 详情图片」的消息链，供命令与 LLM 工具共用。"""
    from astrbot.api.message_components import Image, Plain

    lines = []
    title = _text(detail.get("title"))
    if title:
        lines.append(f"【{title}】")
    event_id = _text(detail.get("id"))
    if event_id:
        lines.append(f"活动页面：{BAONLY_EVENT_URL.format(event_id=event_id)}")
    ticket_url = _text(detail.get("mobileTicketUrl")) or _text(
        detail.get("pcTicketUrl")
    )
    if ticket_url:
        lines.append(f"购票链接：{ticket_url}")

    chain = []
    if lines:
        chain.append(Plain("\n".join(lines)))
    chain.append(Image.fromFileSystem(image_path))
    return chain


# --------------------------------------------------------------------------
# 渲染
# --------------------------------------------------------------------------


def _normalize_local_path(value: str) -> str:
    """把渲染结果统一成本地文件路径。"""
    if value.startswith("file://"):
        from urllib.request import url2pathname
        from urllib.parse import urlparse

        return url2pathname(urlparse(value).path)
    return value


async def _render_with_astrbot(html_text: str) -> str:
    """使用 AstrBot 自带 html_render 渲染，返回本地文件路径。"""
    from astrbot.api import html_renderer

    result = await html_renderer.render_custom_template(
        html_text,
        {},
        return_url=False,
        options={"full_page": True, "type": "jpeg", "quality": 90},
    )
    return _normalize_local_path(result)


def _build_proxy_args(proxy_host, proxy_port, proxy_username, proxy_password):
    if not (proxy_host and proxy_port):
        return None
    if proxy_username and proxy_password:
        return (
            f"http://{proxy_username}:{proxy_password}"
            f"@{proxy_host}:{proxy_port}"
        )
    return f"http://{proxy_host}:{proxy_port}"


# 内置 Chromium 缺失或版本不匹配时，回退到系统浏览器
_SYSTEM_BROWSER_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/microsoft-edge",
)


def _find_system_browser() -> str:
    for path in _SYSTEM_BROWSER_CANDIDATES:
        if os.path.exists(path):
            return path
    return ""


async def _launch_chromium(p, launch_args):
    """优先使用 Playwright 内置 Chromium，缺失时回退系统浏览器。"""
    try:
        return await p.chromium.launch(headless=True, args=launch_args)
    except Exception as e:
        executable = _find_system_browser()
        if not executable:
            raise
        logger.warning(
            f"[BAOnly] Playwright 内置 Chromium 不可用（{e}），"
            f"改用系统浏览器: {executable}"
        )
        return await p.chromium.launch(
            headless=True, args=launch_args, executable_path=executable
        )


async def _render_with_playwright(
    html_text: str,
    output_path: str,
    user_agent: str = "",
    proxy_host: str = "",
    proxy_port: str = "",
    proxy_username: str = "",
    proxy_password: str = "",
) -> str:
    """使用本地 Playwright 渲染，返回本地文件路径。"""
    from playwright.async_api import async_playwright

    proxy_server = _build_proxy_args(
        proxy_host, proxy_port, proxy_username, proxy_password
    )

    async with async_playwright() as p:
        launch_args = ["--disable-blink-features=AutomationControlled"]
        if proxy_server:
            launch_args.append(f"--proxy-server={proxy_server}")
        browser = await _launch_chromium(p, launch_args)
        try:
            context = await browser.new_context(
                viewport={"width": CARD_WIDTH, "height": 900},
                device_scale_factor=2,
                user_agent=user_agent or None,
            )
            page = await context.new_page()
            await page.set_content(html_text, wait_until="networkidle", timeout=30000)
            # 等待网页字体（Blueaka）就绪，否则会截到回退字体
            try:
                await page.evaluate("() => document.fonts.ready")
            except Exception:
                pass
            # 等待所有图片解码完成，避免出现空白占位
            try:
                await page.evaluate("""
                    async () => {
                        const imgs = [...document.querySelectorAll('img')];
                        await Promise.all(imgs.map(img => img.decode().catch(() => {})));
                    }
                """)
            except Exception:
                pass
            await page.wait_for_timeout(300)
            await page.screenshot(path=output_path, full_page=True)
        finally:
            await browser.close()
    return output_path


async def render_detail_card(
    detail: dict,
    mode: str = "auto",
    output_dir: str = "",
    user_agent: str = "",
    astrbot_version: str = "",
    plugin_name: str = "",
    plugin_version: str = "",
    proxy_host: str = "",
    proxy_port: str = "",
    proxy_username: str = "",
    proxy_password: str = "",
) -> str:
    """渲染展会详情卡片，返回本地图片路径。

    mode: ``auto`` | ``astrbot`` | ``playwright``
    """
    html_text = build_detail_card_html(
        detail, astrbot_version, plugin_name, plugin_version
    )
    output_dir = output_dir or os.path.join(
        os.path.abspath("data"), "temp", PLUGIN_NAME
    )
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(
        output_dir, f"baonly_detail_{int(time.time() * 1000)}.png"
    )

    async def _via_playwright() -> str:
        return await _render_with_playwright(
            html_text,
            output_path,
            user_agent=user_agent,
            proxy_host=proxy_host,
            proxy_port=proxy_port,
            proxy_username=proxy_username,
            proxy_password=proxy_password,
        )

    async def _via_astrbot() -> str:
        # 远端返回的是临时文件，复制到插件输出目录以便统一管理
        temp_path = await _render_with_astrbot(html_text)
        shutil.copyfile(temp_path, output_path)
        return output_path

    mode = (mode or "auto").lower()

    if mode == "playwright":
        return await _via_playwright()
    if mode == "astrbot":
        return await _via_astrbot()

    try:
        return await _via_astrbot()
    except Exception as e:
        logger.warning(f"[BAOnly] AstrBot 文转图渲染失败，回退本地 Playwright: {e}")
        return await _via_playwright()
