import json

import httpx
from pydantic import Field
from pydantic.dataclasses import dataclass

from astrbot.api import logger
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext

BAONLY_API_URL = "https://api.baonly.cn/api/public/events"


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

        status = kwargs.get("status", "upcoming")
        include_past = kwargs.get("include_past", False)
        city = kwargs.get("city", "")

        headers = {
            "Host": "api.baonly.cn",
            "User-Agent": user_agent,
            "Authorization": f"Bearer {token}",
        }

        is_all = status == "all"
        params = {
            "status": status if not is_all else "upcoming",
            "includePast": str(include_past or is_all).lower(),
        }

        logger.info(f"[BAOnly] 查询活动 API, params={params}")

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(BAONLY_API_URL, headers=headers, params=params)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"[BAOnly] API 请求失败: {e.response.status_code} {e.response.text}"
            )
            return json.dumps(
                {"error": f"API 请求失败，状态码: {e.response.status_code}"},
                ensure_ascii=False,
            )
        except httpx.RequestError as e:
            logger.error(f"[BAOnly] 网络请求异常: {e}")
            return json.dumps(
                {"error": f"网络请求失败: {str(e)}"}, ensure_ascii=False
            )

        events = data.get("events", [])
        stats = data.get("stats", {})

        if city:
            events = [
                e
                for e in events
                if city in e.get("location", {}).get("city", "")
            ]

        result = {
            "total_events": stats.get("total", len(events)),
            "upcoming": stats.get("upcoming", 0),
            "ongoing": stats.get("ongoing", 0),
            "past": stats.get("past", 0),
            "query": {
                "status": status,
                "city": city,
                "include_past": include_past,
            },
            "events_count": len(events),
            "events": [
                {
                    "title": e.get("title"),
                    "timeLabel": e.get("timeLabel"),
                    "startAt": e.get("startAt"),
                    "endAt": e.get("endAt"),
                    "province": e.get("location", {}).get("province"),
                    "city": e.get("location", {}).get("city"),
                    "venueName": e.get("location", {}).get("venueName"),
                    "address": e.get("location", {}).get("address"),
                    "priceLabel": e.get("priceLabel"),
                    "saleFlag": e.get("saleFlag"),
                    "organizer": e.get("organizer", {}).get("name"),
                    "tags": e.get("tags", []),
                    "status": e.get("status"),
                    "detailUrl": f"https://www.baonly.cn{e.get('detailUrl', '')}",
                }
                for e in events
            ],
        }

        return json.dumps(result, ensure_ascii=False)
