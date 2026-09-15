import json

import httpx
from pydantic import Field
from pydantic.dataclasses import dataclass

from astrbot.api import logger
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext

BAONLY_API_BASE = "https://beta.baonly.cn/api/public"

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

    headers = {
        "User-Agent": user_agent,
        "x-api-key": token,
    }

    is_all = status == "all"
    params = {
        "status": status if not is_all else "upcoming",
        "includePast": str(include_past or is_all).lower(),
    }

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

    return {
        "total": total,
        "page": data.get("page", 1),
        "pageSize": data.get("pageSize", page_size),
        "pageCount": data.get("pageCount", 0),
        "query": {
            "status": status,
            "city": city,
            "province": province,
            "tag": tag,
            "include_past": include_past,
        },
        "events_count": len(items),
        "events": [_map_event_list_item(e) for e in items],
    }


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
        "province": city.get("province") or city.get("name"),
        "city": city.get("name"),
        "cityId": city.get("id"),
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
        "返回活动列表，包含活动名称(title)、时间(startAt/endAt/timeLabel)、"
        "地点(province/city/venueName/address)、票价(priceLabel)、"
        "售票状态(saleFlag)、主办方(organizer)、标签(tags)等详细信息。"
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
                "sort": {
                    "type": "string",
                    "description": "排序方式。timeAsc=按时间升序，startAsc=开始时间升序，"
                    "priceAsc=价格升序。默认 timeAsc。",
                    "enum": ["timeAsc", "startAsc", "startDesc", "priceAsc", "priceDesc"],
                },
                "page_size": {
                    "type": "integer",
                    "description": "每页返回条数，默认 20，最大 50。",
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
