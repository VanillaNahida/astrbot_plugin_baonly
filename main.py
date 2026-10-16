from __future__ import annotations

from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.star.filter.command import GreedyStr

from .modules.api import ApiError
from .modules.api.mapping import map_detail
from .modules.cards import help_text
from .modules.events.text import format_event_detail, format_event_list
from .modules.screenshot import DEFAULT_PAGE_SIZE, PAGE_SIZES
from .modules.services import PluginServices
from .modules.subscriptions import Subscription
from .modules.tools import EventDetailTool, EventImageTool, QueryEventsTool
from .utils.log import log

MEMBER = filter.PermissionType.MEMBER
ADMIN = filter.PermissionType.ADMIN


class BaonlyPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.svc = PluginServices.build(context, config)
        self.svc.webui.register(context)
        context.add_llm_tools(
            QueryEventsTool(services=self.svc),
            EventDetailTool(services=self.svc),
            EventImageTool(services=self.svc),
        )
        log.info("插件已初始化，LLM 工具已注册")

    async def initialize(self):
        self.svc.notifier.start()

    async def terminate(self):
        await self.svc.aclose()
        log.info("插件已卸载")

    @filter.permission_type(MEMBER)
    @filter.command("bao", alias={"BAO"}, desc="截图 Baonly 网页活动列表，默认每页 8 场")
    async def bao(self, event: AstrMessageEvent):
        async for result in self._screenshot(event, DEFAULT_PAGE_SIZE):
            yield result

    @filter.command_group("baonly")
    async def baonly(self):
        pass

    @filter.permission_type(MEMBER)
    @baonly.command("page", desc="截图 Baonly 网页活动列表，可指定每页显示数量(4/6/8/10/20/23/50) 如：baonly page 8")
    async def page(self, event: AstrMessageEvent, page_size: int = DEFAULT_PAGE_SIZE):
        if page_size not in PAGE_SIZES:
            yield event.plain_result(f"不支持的每页数量: {page_size}，可选值: {', '.join(map(str, PAGE_SIZES))}")
            return
        async for result in self._screenshot(event, page_size):
            yield result

    @filter.permission_type(MEMBER)
    @baonly.command(
        "query",
        desc="查询 Baonly 展会列表。用法：baonly query [status] [city]\nstatus 可选：upcoming/ongoing/past/all，city 如：深圳市",
    )
    async def query(self, event: AstrMessageEvent, status: str = "upcoming", city: str = ""):
        catalog = self.svc.catalog
        try:
            result = await catalog.query(catalog.build_query({"status": status, "city": city}))
        except ApiError as exc:
            yield event.plain_result(f"查询失败: {exc}")
            return
        yield event.plain_result(format_event_list(result, status, city))

    @filter.permission_type(MEMBER)
    @baonly.command(
        "detail",
        desc="查询单个 Baonly 展会详情。支持活动ID，也支持标题/主办方/城市/场馆等关键词检索。\n用法：baonly detail <活动ID|关键词>",
    )
    async def detail(self, event: AstrMessageEvent, keyword: GreedyStr):
        query = str(keyword or "").strip()
        if not query:
            yield event.plain_result("请提供活动ID或关键词，例如：baonly detail 广州蔚蓝档案")
            return

        try:
            data = await self.svc.catalog.resolve(query)
        except ApiError as exc:
            yield event.plain_result(f"查询失败: {exc}")
            return
        if data is None:
            yield event.plain_result(f"未找到匹配「{query}」的活动，请换个关键词试试。")
            return

        if self.svc.settings.detail_image_enabled:
            cards = self.svc.detail_cards
            try:
                image = await cards.render(data)
                yield event.chain_result(cards.reply_chain(data, image))
                return
            except Exception as exc:
                log.error(f"生成展会详情图片失败，回退文本输出: {exc}", exc_info=True)

        yield event.plain_result(format_event_detail(map_detail(data)))

    @filter.permission_type(ADMIN)
    @baonly.command("sub", alias={"subscribe"}, desc="订阅当前会话，活动变更时自动推送。用法：baonly sub")
    async def sub(self, event: AstrMessageEvent):
        subscription = await self._current_subscription(event, with_display=True)
        if await self.svc.subscriptions.add(subscription):
            yield event.plain_result("已订阅当前会话，展会变更将自动推送。")
        else:
            yield event.plain_result("当前会话已在订阅列表中，无需重复订阅。")

    @filter.permission_type(ADMIN)
    @baonly.command("unsub", alias={"unsubscribe"}, desc="取消订阅当前会话。用法：baonly unsub")
    async def unsub(self, event: AstrMessageEvent):
        subscription = await self._current_subscription(event)
        removed = await self.svc.subscriptions.remove(subscription.umo)
        yield event.plain_result("已取消订阅当前会话。" if removed else "当前会话未在订阅列表中。")

    @filter.permission_type(MEMBER)
    @baonly.command("status", desc="查看订阅推送连接状态。用法：baonly status")
    async def status(self, event: AstrMessageEvent):
        yield event.plain_result("\n".join(self.svc.notifier.describe_status()))

    @filter.permission_type(MEMBER)
    @baonly.command("list", desc="查看当前全部订阅渠道。用法：baonly list")
    async def list_subscriptions(self, event: AstrMessageEvent):
        subs = await self.svc.subscriptions.list()
        if not subs:
            yield event.plain_result("当前没有订阅任何渠道。")
            return
        lines = [f"共 {len(subs)} 个订阅渠道："]
        for index, sub in enumerate(subs, start=1):
            name = await self.svc.contacts.display_name(sub.is_group, sub.channel, sub.display)
            kind = "群" if sub.is_group else "私聊"
            lines.append(f"{index}.{kind}：{name}({sub.channel})")
        lines.append("可使用 baonly sub/unsub 维护订阅渠道，也可在 WebUI 插件页管理。")
        yield event.plain_result("\n".join(lines))

    @filter.permission_type(MEMBER)
    @baonly.command("help", desc="查看插件使用方法（渲染成图片发送）。用法：baonly help")
    async def help(self, event: AstrMessageEvent):
        try:
            yield event.image_result(str(await self.svc.help_cards.render()))
            return
        except Exception as exc:
            log.error(f"生成帮助图片失败，回退文本输出: {exc}", exc_info=True)
        yield event.plain_result(help_text())

    async def _screenshot(self, event: AstrMessageEvent, page_size: int):
        yield event.plain_result(f"正在截图，页数：{page_size}，请稍后……")
        try:
            yield event.image_result(str(await self.svc.screenshots.capture(page_size)))
        except Exception as exc:
            log.error(f"截图失败: {exc}", exc_info=True)
            yield event.plain_result(f"截图失败: {exc}")

    async def _current_subscription(self, event: AstrMessageEvent, with_display: bool = False) -> Subscription:
        group_id = str(getattr(event.message_obj, "group_id", "") or "")
        is_group = bool(group_id)
        channel_id = group_id if is_group else str(event.get_sender_id())
        display = await self.svc.contacts.display_name(is_group, channel_id) if with_display else ""
        return Subscription.create(event.unified_msg_origin, is_group, channel_id, display)
