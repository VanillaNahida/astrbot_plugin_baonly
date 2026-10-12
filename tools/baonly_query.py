import json

import httpx
from pydantic import Field
from pydantic.dataclasses import dataclass

from astrbot.api import logger
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext

from ..time_utils import format_time_range

BAONLY_API_BASE = "https://www.baonly.cn/api/public"

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)


async def fetch_events_list(token: str, user_agent: str, **kwargs) -> dict:
    """查询活动列表，返回结构化 dict（不抛异常，出错时含 error 字段）。"""
    status = kwargs.get("status", "upcoming")
    include_past = bool(kwargs.get("include_past", False))
    city = kwargs.get("city", "")
    province = kwargs.get("province", "")
    tag = kwargs.get("tag", "")
    sort = kwargs.get("sort", "timeAsc")
    page_size = kwargs.get("page_size", 20)
    page = kwargs.get("page", 1)

    headers = {
        "User-Agent": user_agent,
        "x-api-key": token,
    }

    is_all = status == "all"
    params = {
        "status": status,
        "includePast": str(include_past or is_all).lower(),
    }

    if page:
        params["page"] = page
    if city:
        params["cityName"] = city
    if province:
        params["province"] = province
    if tag:
        params["tag"] = tag
    if sort:
        params["sort"] = sort
    if page_size:
        params["pageSize"] = page_size

    # 以下为 openapi.json 同步的新增查询参数
    if kwargs.get("q"):
        params["q"] = kwargs["q"]
    if kwargs.get("updated_since"):
        params["updatedSince"] = kwargs["updated_since"]
    if kwargs.get("region"):
        params["region"] = kwargs["region"]
    if kwargs.get("city_id"):
        params["cityId"] = kwargs["city_id"]
    if kwargs.get("min_price_cents") is not None:
        params["minPriceCents"] = kwargs["min_price_cents"]
    if kwargs.get("max_price_cents") is not None:
        params["maxPriceCents"] = kwargs["max_price_cents"]
    if kwargs.get("date_mode"):
        params["dateMode"] = kwargs["date_mode"]
    if kwargs.get("date"):
        params["date"] = kwargs["date"]
    if kwargs.get("date_from"):
        params["dateFrom"] = kwargs["date_from"]
    if kwargs.get("date_to"):
        params["dateTo"] = kwargs["date_to"]
    if kwargs.get("highlighted_only"):
        params["highlightedOnly"] = "true"
    if kwargs.get("featured_only"):
        params["featuredOnly"] = "true"
    if kwargs.get("carousel_only"):
        params["carouselOnly"] = "true"
    if kwargs.get("marker"):
        params["marker"] = kwargs["marker"]
    if kwargs.get("holiday_name"):
        params["holidayName"] = kwargs["holiday_name"]
    if kwargs.get("lat") is not None:
        params["lat"] = kwargs["lat"]
    if kwargs.get("lng") is not None:
        params["lng"] = kwargs["lng"]
    if kwargs.get("max_distance_km") is not None:
        params["maxDistanceKm"] = kwargs["max_distance_km"]
    if kwargs.get("facets") is not None:
        params["facets"] = str(bool(kwargs["facets"])).lower()

    url = f"{BAONLY_API_BASE}/events"

    logger.info(f"[BAOnly] 查询活动 API, url={url}, params={params}")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        logger.error(
            f"[BAOnly] API 请求失败: {e.response.status_code} {e.response.text}"
        )
        return {"error": f"API 请求失败，状态码: {e.response.status_code}"}
    except httpx.RequestError as e:
        logger.error(f"[BAOnly] 网络请求异常: {e}")
        return {"error": f"网络请求失败: {str(e)}"}

    items = data.get("items", [])
    total = data.get("total", 0)

    # 客户端再按城市过滤一次，兜底（服务端 cityName 未必精确匹配）
    if city:
        items = [
            e
            for e in items
            if city in _safe_str((e.get("city") or {}).get("name"))
            or city in _safe_str((e.get("city") or {}).get("province"))
        ]

    # 本地记录 id -> 活动名称对照，便于本地反查
    from ..event_name_map import record_events

    await record_events(items)

    result = {
        "total": total,
        "page": data.get("page", 1),
        "pageSize": data.get("pageSize", page_size),
        "pageCount": data.get("pageCount", 0),
        "query": {
            "status": status,
            "city": city,
            "province": province,
            "tag": tag,
            "marker": kwargs.get("marker", ""),
            "include_past": include_past,
        },
        "events_count": len(items),
        "events": [_map_event_list_item(e) for e in items],
    }

    # 筛选面板计数（facets）体积较大，仅在显式请求时回传
    if kwargs.get("facets") is not None:
        result["facets"] = data.get("facets")

    return result


def _safe_str(value, default=""):
    if value is None:
        return default
    return str(value)


def _map_event_list_item(item):
    """把 beta 站列表项字段映射为对外字段名"""
    city = item.get("city") or {}
    venue = item.get("venue") or {}
    organizer = item.get("organizer") or {}
    tags = item.get("tags") or []
    dates = item.get("dates") or []
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
        "tags": [t.get("name") for t in tags],
        "dates": [d.get("date") for d in dates],
    }


@dataclass
class BAOnlyQueryTool(FunctionTool[AstrAgentContext]):
    name: str = "baonly_query_events"
    description: str = (
        "查询蔚蓝档案(Blue Archive) BAONLY 同人展活动信息。"
        "返回活动列表，包含活动名称(title)、时间(timeText：已按东八区格式化的标准时间，"
        "如 2026.09.30 - 2026.10.01；startAt/endAt 为 ISO 标准时间，"
        "timeLabel 仅为源站原始文案，无标准时间时才使用)、"
        "地点(province/city/venueName/address)、票价(priceLabel)、"
        "售票状态(saleFlag)、主办方(organizer)、标签(tags)、"
        "运营标记(markers：已取消/已延期/地点变更)等详细信息。"
        "向用户播报时间时请使用 timeText 或依据 startAt/endAt 换算，不要直接照抄 timeLabel。"
        "可用于回答用户关于蔚蓝档案ONLY/同人展活动的查询。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": (
                        "活动状态筛选。upcoming=即将举行，ongoing=进行中，"
                        "past=已结束，all=全部。默认 upcoming。"
                    ),
                    "enum": ["upcoming", "ongoing", "past", "all"],
                },
                "include_past": {
                    "type": "boolean",
                    "description": "是否包含已结束的活动，默认 false。",
                },
                "city": {
                    "type": "string",
                    "description": (
                        "按城市名称筛选活动，例如'深圳市'、'上海市'、'广州市'。"
                        "不填则返回全部城市。"
                    ),
                },
                "province": {
                    "type": "string",
                    "description": "按省份名称筛选活动，例如\"广东省\"。",
                },
                "tag": {
                    "type": "string",
                    "description": "按标签筛选活动，例如\"ONLY\"、\"同人展\"。",
                },
                "marker": {
                    "type": "string",
                    "description": (
                        "按运营标记筛选活动。cancelled=已取消，"
                        "postponed=已延期，venueChanged=地点变更。"
                    ),
                    "enum": ["cancelled", "postponed", "venueChanged"],
                },
                "q": {
                    "type": "string",
                    "description": "按活动标题关键字筛选。",
                },
                "region": {
                    "type": "string",
                    "description": "按大区筛选活动，例如\"华东\"、\"华南\"。",
                },
                "city_id": {
                    "type": "string",
                    "description": "按城市 ID 精确筛选，取值来自城市计数（facets）里的 value。",
                },
                "date_mode": {
                    "type": "string",
                    "description": (
                        "日期筛选模式。holiday=按节假日，day=按单日（配合 date），"
                        "range=按区间（配合 date_from/date_to）。"
                    ),
                    "enum": ["", "holiday", "day", "range"],
                },
                "holiday_name": {
                    "type": "string",
                    "description": "节假日名称，配合 date_mode=holiday 使用，例如\"国庆节\"。",
                },
                "min_price_cents": {
                    "type": "integer",
                    "description": "最低票价下限，单位分（例如 6000 表示 60 元）。",
                },
                "max_price_cents": {
                    "type": "integer",
                    "description": "最高票价上限，单位分（例如 15000 表示 150 元）。",
                },
                "highlighted_only": {
                    "type": "boolean",
                    "description": "只返回带高亮（含高亮标签或运营标记）的活动。",
                },
                "carousel_only": {
                    "type": "boolean",
                    "description": "只返回进入首页海报轮播的精选活动。",
                },
                "lat": {
                    "type": "number",
                    "description": "纬度，与 lng 一起传入可开启距离排序（sort=distance）。",
                },
                "lng": {
                    "type": "number",
                    "description": "经度，与 lat 一起传入可开启距离排序（sort=distance）。",
                },
                "max_distance_km": {
                    "type": "number",
                    "description": "按距离筛选的最大半径（公里），需同时传 lat/lng，取值 1~5000。",
                },
                "date": {
                    "type": "string",
                    "description": "按具体日期筛选活动，格式 yyyy-MM-dd，例如 2026-10-01。",
                },
                "date_from": {
                    "type": "string",
                    "description": "按日期范围筛选（起始），格式 yyyy-MM-dd。",
                },
                "date_to": {
                    "type": "string",
                    "description": "按日期范围筛选（结束），格式 yyyy-MM-dd。",
                },
                "featured_only": {
                    "type": "boolean",
                    "description": "只返回运营精选的活动。",
                },
                "updated_since": {
                    "type": "string",
                    "description": (
                        "只返回这个时间点之后改动过的场次（ISO 8601 时间串），"
                        "用于断线重连后的增量对齐。"
                    ),
                },
                "sort": {
                    "type": "string",
                    "description": "排序方式。timeAsc=按时间升序，startAsc=开始时间升序，"
                    "priceAsc=价格升序，distance=按距离升序（需传 lat/lng）。默认 timeAsc。",
                    "enum": [
                        "timeAsc",
                        "startAsc",
                        "startDesc",
                        "priceAsc",
                        "priceDesc",
                        "distance",
                    ],
                },
                "page_size": {
                    "type": "integer",
                    "description": "每页返回条数，默认 20，最大 500。",
                },
            },
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
        data = await fetch_events_list(token, user_agent, **kwargs)
        return json.dumps(data, ensure_ascii=False)
