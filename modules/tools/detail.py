from __future__ import annotations

from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext
from pydantic import Field
from pydantic.dataclasses import dataclass

from ...utils.text import clean
from ..api import ApiError
from .base import BaonlyTool, error_json, to_json

DESCRIPTION = (
    "查询蔚蓝档案(Blue Archive) BAONLY 同人展活动的详细信息。"
    "传入活动 id(从 baonly_query_events 获得)，返回该活动的详细资料，"
    "包括完整的介绍(description)、票档(tickets)、嘉宾(guests)、"
    "场馆(address)、主办方、购票链接等。"
    "时间字段中 timeText 是由标准时间(startAt/endAt，东八区)格式化好的展示文案，"
    "timeLabel 仅为源站原始文案，向用户播报时间请用 timeText / startAt。"
    "用于回答用户对某个具体展会的深入查询。"
)

EVENT_ID_PARAMETERS = {
    "type": "object",
    "properties": {"event_id": {"type": "string", "description": "活动 id，来自活动列表查询结果。"}},
    "required": ["event_id"],
}


@dataclass
class EventDetailTool(BaonlyTool):
    name: str = "baonly_event_detail"
    description: str = DESCRIPTION
    parameters: dict = Field(default_factory=lambda: EVENT_ID_PARAMETERS)

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        event_id = clean(kwargs.get("event_id"))
        if not event_id:
            return error_json("缺少 event_id 参数")
        try:
            return to_json(await self.svc.catalog.detail(event_id))
        except ApiError as exc:
            return error_json(str(exc))
