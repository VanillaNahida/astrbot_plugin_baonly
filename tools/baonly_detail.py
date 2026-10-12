import json
import re

import httpx
from pydantic import Field
from pydantic.dataclasses import dataclass

from astrbot.api import logger
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext

from .baonly_query import BAONLY_API_BASE, fetch_events_list
from ..time_utils import format_time_range


async def fetch_event_detail(token: str, user_agent: str, event_id: str) -> dict:
    """查询单个活动详情，返回结构化 dict；404 时包含 'not_found' 标记。"""
    url = f"{BAONLY_API_BASE}/events/{event_id}"
    headers = {
        "User-Agent": user_agent,
        "x-api-key": token,
    }

    logger.info(f"[BAOnly] 查询活动详情 API, url={url}")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 404:
                return {"not_found": True, "error": "未找到该活动，可能已删除或已下架"}
            resp.raise_for_status()
            data = resp.json()
            # 本地记录 id -> 活动名称对照
            from ..event_name_map import record_event

            await record_event(data.get("id"), data.get("title"))
            return data
    except httpx.HTTPStatusError as e:
        logger.error(
            f"[BAOnly] API 请求失败: {e.response.status_code} {e.response.text}"
        )
        return {"error": f"API 请求失败，状态码: {e.response.status_code}"}
    except httpx.RequestError as e:
        logger.error(f"[BAOnly] 网络请求异常: {e}")
        return {"error": f"网络请求失败: {str(e)}"}


def _map_event_detail(item):
    """把 beta 站活动详情字段映射为对外字段名"""
    city = item.get("city") or {}
    venue = item.get("venue") or {}
    organizer = item.get("organizer") or {}
    cover = item.get("cover") or {}
    banner = item.get("banner") or {}
    tags = item.get("tags") or []
    tickets = item.get("tickets") or []
    guests = item.get("guests") or []
    info_items = item.get("infoItems") or []
    change_notices = item.get("changeNotices") or []
    detail_images = item.get("detailImages") or []

    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "timeText": format_time_range(
            item.get("startAt"), item.get("endAt"), item.get("timeLabel")
        ),
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
        "organizer": organizer.get("name"),
        "tags": [
            {
                "name": t.get("name"),
                "color": t.get("color"),
                "highlight": t.get("highlight"),
                "beforeTitle": t.get("beforeTitle"),
            }
            for t in tags
        ],
        "description": item.get("description"),
        "coverUrl": cover.get("url"),
        "bannerUrl": banner.get("url"),
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
            for t in tickets
        ],
        "guests": [
            {
                "name": g.get("name"),
                "description": g.get("description"),
                "imageUrl": (g.get("image") or {}).get("url"),
            }
            for g in guests
        ],
        "infoItems": [
            {
                "id": i.get("id"),
                "section": i.get("section"),
                "title": i.get("title"),
                "content": i.get("content"),
            }
            for i in info_items
        ],
        "changeNotices": [
            {
                "field": n.get("field"),
                "oldValue": n.get("oldValue"),
                "newValue": n.get("newValue"),
                "noticedAt": n.get("noticedAt"),
            }
            for n in change_notices
        ],
        "detailImages": detail_images,
        "pcTicketUrl": item.get("pcTicketUrl"),
        "mobileTicketUrl": item.get("mobileTicketUrl"),
    }


_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# 文字检索时各字段的权重
_FIELD_WEIGHTS = (
    ("title", 60),
    ("organizer", 45),
    ("city", 35),
    ("province", 30),
    ("venueName", 25),
    ("address", 20),
)


def looks_like_id(value: str) -> bool:
    """判断输入是否像活动 ID（纯字母数字下划线连字符）。"""
    return bool(_ID_PATTERN.match((value or "").strip()))


def _score_event(event: dict, tokens: list) -> int:
    """按标题/主办/城市/省份/场馆/地址给候选活动打分，0 表示不匹配。"""
    fields = {
        key: str(event.get(key) or "").lower() for key, _ in _FIELD_WEIGHTS
    }
    tags = " ".join(str(t) for t in (event.get("tags") or [])).lower()

    matched = 0
    total = 0
    for token in tokens:
        best = 0
        for key, weight in _FIELD_WEIGHTS:
            value = fields[key]
            if not value:
                continue
            if value == token:
                best = max(best, weight + 40)
            elif token in value:
                best = max(best, weight)
        if not best and token in tags:
            best = 15
        if best:
            matched += 1
            total += best

    if not matched:
        return 0
    # 匹配到的关键词越多越优先；未结束的活动略微加权
    total += matched * 20
    state = event.get("state")
    if state == "ongoing":
        total += 8
    elif state == "upcoming":
        total += 5
    return total


async def _search_candidates(token: str, user_agent: str, query: str) -> list:
    """按关键词检索候选活动，优先服务端标题匹配，无结果时放宽到全量列表。"""
    collected = {}

    data = await fetch_events_list(
        token,
        user_agent,
        q=query,
        status="all",
        include_past=True,
        page_size=50,
    )
    for item in data.get("events") or []:
        event_id = str(item.get("id") or "")
        if event_id:
            collected[event_id] = item

    if collected:
        return list(collected.values())

    # 主办方/城市/场馆等字段服务端不参与 q 匹配，这里拉取较宽的活动集本地打分
    data = await fetch_events_list(
        token,
        user_agent,
        status="all",
        include_past=True,
        page_size=200,
    )
    for item in data.get("events") or []:
        event_id = str(item.get("id") or "")
        if event_id:
            collected[event_id] = item
    return list(collected.values())


async def resolve_event(token: str, user_agent: str, query: str):
    """把用户输入解析为 ``(event_id, 原始详情dict)``，无法匹配时返回 ``(None, None)``。

    输入既可以是活动 ID，也可以是标题 / 主办方 / 城市 / 场馆等文字描述。
    """
    query = (query or "").strip()
    if not query:
        return None, None

    if looks_like_id(query):
        data = await fetch_event_detail(token, user_agent, query)
        if not (data.get("not_found") or data.get("error")):
            return query, data

    tokens = [t for t in re.split(r"[\s,，、]+", query.lower()) if t]
    candidates = await _search_candidates(token, user_agent, query)
    if not candidates or not tokens:
        return None, None

    best = max(candidates, key=lambda item: _score_event(item, tokens))
    if _score_event(best, tokens) <= 0:
        return None, None

    event_id = str(best.get("id") or "")
    if not event_id:
        return None, None

    data = await fetch_event_detail(token, user_agent, event_id)
    if data.get("not_found") or data.get("error"):
        return event_id, None
    return event_id, data


@dataclass
class BAOnlyEventDetailTool(FunctionTool[AstrAgentContext]):
    name: str = "baonly_event_detail"
    description: str = (
        "查询蔚蓝档案(Blue Archive) BAONLY 同人展活动的详细信息。"
        "传入活动 id(从 baonly_query_events 获得)，返回该活动的详细资料，"
        "包括完整的介绍(description)、票档(tickets)、嘉宾(guests)、"
        "场馆(address)、主办方、购票链接等。"
        "时间字段中 timeText 是由标准时间(startAt/endAt，东八区)格式化好的展示文案，"
        "timeLabel 仅为源站原始文案，向用户播报时间请用 timeText / startAt。"
        "用于回答用户对某个具体展会的深入查询。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "活动 id，来自活动列表查询结果。",
                },
            },
            "required": ["event_id"],
        }
    )

    # 插件配置，由 main.py 在注册前注入
    _config: dict = Field(default_factory=dict, repr=False, exclude=True)

    def set_config(self, config: dict):
        self._config = config

    async def call(
        self, context: ContextWrapper[AstrAgentContext], **kwargs
    ) -> ToolExecResult:
        token = self._config.get("token", "")
        user_agent = self._config.get(
            "user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
        )

        event_id = kwargs.get("event_id", "")

        if not event_id:
            return json.dumps({"error": "缺少 event_id 参数"}, ensure_ascii=False)

        data = await fetch_event_detail(token, user_agent, event_id)

        if data.get("not_found"):
            return json.dumps({"error": data.get("error")}, ensure_ascii=False)

        if data.get("error"):
            return json.dumps({"error": data.get("error")}, ensure_ascii=False)

        return json.dumps(_map_event_detail(data), ensure_ascii=False)
