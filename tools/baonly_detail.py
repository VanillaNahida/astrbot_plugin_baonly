import json

import httpx
from pydantic import Field
from pydantic.dataclasses import dataclass

from astrbot.api import logger
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext

from .baonly_query import BAONLY_API_BASE


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
        "description": item.get("description"),
        "coverUrl": cover.get("url"),
        "bannerUrl": banner.get("url"),
        "tickets": [
            {
                "name": t.get("name"),
                "priceCents": t.get("priceCents"),
                "priceLabel": t.get("priceLabel"),
                "saleFlag": t.get("saleFlag"),
            }
            for t in tickets
        ],
        "guests": [
            {"name": g.get("name"), "description": g.get("description")}
            for g in guests
        ],
        "infoItems": [
            {"section": i.get("section"), "title": i.get("title"), "content": i.get("content")}
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


@dataclass
class BAOnlyEventDetailTool(FunctionTool[AstrAgentContext]):
    name: str = "baonly_event_detail"
    description: str = (
        "查询蔚蓝档案(Blue Archive) BAONLY 同人展活动的详细信息。"
        "传入活动 id(从 baonly_query_events 获得)，返回该活动的详细资料，"
        "包括完整的介绍(description)、票档(tickets)、嘉宾(guests)、"
        "场馆(address)、主办方、购票链接等。"
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
