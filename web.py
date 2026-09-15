from astrbot.api.web import error_response, json_response, request

from .page_service import SubscriptionPageService

PLUGIN_NAME = "astrbot_plugin_baonly"


class BAOnlyWebController:
    """插件 Page 后端路由：订阅渠道管理。"""

    def __init__(self, service: SubscriptionPageService):
        self.service = service

    def register_routes(self, context) -> None:
        context.register_web_api(
            f"/{PLUGIN_NAME}/subscriptions/list",
            self.page_list,
            ["GET"],
            "订阅渠道列表",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/subscriptions/groups",
            self.page_groups,
            ["GET"],
            "可用群列表",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/subscriptions/add",
            self.page_add,
            ["POST"],
            "新增订阅渠道",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/subscriptions/remove",
            self.page_remove,
            ["POST"],
            "移除订阅渠道",
        )

    async def page_list(self):
        data = await self.service.list_subscriptions()
        return json_response(data)

    async def page_groups(self):
        groups = await self.service.list_available_groups()
        return json_response({"groups": groups})

    async def page_add(self):
        payload = await request.json(default={})
        umo = payload.get("umo", "")
        is_group = bool(payload.get("is_group", False))
        channel_id = payload.get("channel_id", "")
        display = payload.get("display", "")
        result = await self.service.add_subscription(
            umo=umo, is_group=is_group, channel_id=channel_id, display=display
        )
        if not result.get("ok"):
            return error_response(result.get("message", "参数错误"), status_code=400)
        return json_response(result)

    async def page_remove(self):
        payload = await request.json(default={})
        umo = payload.get("umo")
        result = await self.service.remove_subscription(umo)
        return json_response(result)
