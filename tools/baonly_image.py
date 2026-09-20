import os

from pydantic import Field
from pydantic.dataclasses import dataclass

from astrbot.api import logger
from astrbot.api.event import MessageChain
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext

from ..detail_card import (
    build_detail_reply_chain,
    render_detail_card,
    render_options_from_config,
)
from .baonly_detail import fetch_event_detail
from .baonly_query import DEFAULT_USER_AGENT

PLUGIN_NAME = "astrbot_plugin_baonly"


@dataclass
class BAOnlyEventImageTool(FunctionTool[AstrAgentContext]):
    name: str = "baonly_event_image"
    description: str = (
        "根据活动 ID 生成该蔚蓝档案 BAONLY 展会的详情卡片图片，"
        "并直接发送给用户（图片包含时间、地点、票价、票档、嘉宾等信息，"
        "同时附带购票链接）。当用户想要某个具体展会的图片或图文详情时调用。"
        "活动 ID 可从 baonly_query_events 的查询结果中获得。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "活动 id，来自 baonly_query_events 的查询结果。",
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
        config = self._config or {}
        event_id = str(kwargs.get("event_id") or "").strip()
        if not event_id:
            return "缺少 event_id 参数，无法生成展会图片。"

        if not bool(config.get("detail_image_enabled", True)):
            return (
                "插件配置中已关闭「详情图片渲染」，无法生成图片。"
                "请告知用户可在插件配置中开启该选项。"
            )

        token = config.get("token", "")
        user_agent = config.get("user_agent", DEFAULT_USER_AGENT)

        data = await fetch_event_detail(token, user_agent, event_id)
        if data.get("not_found") or data.get("error"):
            return f"未找到活动 {event_id}：{data.get('error', '活动不存在或已下架')}"

        output_dir = os.path.abspath(os.path.join("data", "temp", PLUGIN_NAME))
        try:
            image_path = await render_detail_card(
                data, output_dir=output_dir, **render_options_from_config(config)
            )
        except Exception as e:
            logger.error(f"[BAOnly] 生成展会详情图片失败: {e}", exc_info=True)
            return f"生成展会详情图片失败：{e}"

        chain = build_detail_reply_chain(data, image_path)
        try:
            await context.context.context.send_message(
                context.context.event.unified_msg_origin,
                MessageChain(chain=chain),
            )
        except Exception as e:
            logger.error(f"[BAOnly] 发送展会详情图片失败: {e}", exc_info=True)
            return f"图片已生成但发送失败：{e}"

        title = str(data.get("title") or event_id)
        return f"已向用户发送活动「{title}」的详情图片与购票链接。"
