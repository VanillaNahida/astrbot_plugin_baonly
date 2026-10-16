from __future__ import annotations

from astrbot.api.event import MessageChain
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext
from pydantic import Field
from pydantic.dataclasses import dataclass

from ...utils.log import log
from ...utils.text import clean
from ..api import ApiError
from .base import BaonlyTool

DESCRIPTION = (
    "根据活动 ID 生成该蔚蓝档案 BAONLY 展会的详情卡片图片，"
    "并直接发送给用户（图片包含时间、地点、票价、票档、嘉宾等信息，"
    "同时附带购票链接）。当用户想要某个具体展会的图片或图文详情时调用。"
    "活动 ID 可从 baonly_query_events 的查询结果中获得。"
)

PARAMETERS = {
    "type": "object",
    "properties": {"event_id": {"type": "string", "description": "活动 id，来自 baonly_query_events 的查询结果。"}},
    "required": ["event_id"],
}


@dataclass
class EventImageTool(BaonlyTool):
    name: str = "baonly_event_image"
    description: str = DESCRIPTION
    parameters: dict = Field(default_factory=lambda: PARAMETERS)

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        event_id = clean(kwargs.get("event_id"))
        if not event_id:
            return "缺少 event_id 参数，无法生成展会图片。"
        if not self.svc.settings.detail_image_enabled:
            return "插件配置中已关闭「详情图片渲染」，无法生成图片。请告知用户可在插件配置中开启该选项。"

        try:
            detail = await self.svc.catalog.client.get_event(event_id)
        except ApiError as exc:
            return f"未找到活动 {event_id}：{exc}"

        cards = self.svc.detail_cards
        try:
            image = await cards.render(detail)
        except Exception as exc:
            log.error(f"生成展会详情图片失败: {exc}", exc_info=True)
            return f"生成展会详情图片失败：{exc}"

        agent = context.context
        try:
            await agent.context.send_message(
                agent.event.unified_msg_origin, MessageChain(chain=cards.reply_chain(detail, image))
            )
        except Exception as exc:
            log.error(f"发送展会详情图片失败: {exc}", exc_info=True)
            return f"图片已生成但发送失败：{exc}"

        return f"已向用户发送活动「{clean(detail.get('title')) or event_id}」的详情图片与购票链接。"
