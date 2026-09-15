import asyncio
import os
import time
from importlib.metadata import version

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger, AstrBotConfig

from .tools import BAOnlyQueryTool, BAOnlyEventDetailTool
from .tools.baonly_query import fetch_events_list, DEFAULT_USER_AGENT
from .tools.baonly_detail import fetch_event_detail
from .baonly_screenshot import capture_screenshot
from .subscriptions import SubscriptionStore
from .stream_notifier import StreamNotifier
from .group_cache import GroupInfoCache, extract_channel_id
from .page_service import SubscriptionPageService, _resolve_display
from .web import BAOnlyWebController

VALID_PAGE_SIZES = [4, 6, 10, 20, 23, 50]
PLUGIN_NAME = "astrbot_plugin_baonly"
PLUGIN_VERSION = "2.0.0"


def _get_version_safe(package: str) -> str:
    try:
        return version(package)
    except Exception:
        return ""


class BAOnlyPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.config = config if config is not None else {}

        self._astrbot_version = _get_version_safe("astrbot")
        self._plugin_version = PLUGIN_VERSION

        # 订阅存储 / Page 后端 / WS 推送
        self._store = SubscriptionStore()
        self._group_cache = GroupInfoCache(context)
        page_service = SubscriptionPageService(self._store, self._group_cache)
        self._web = BAOnlyWebController(page_service)
        self._web.register_routes(context)

        # LLM 工具
        self._query_tool = BAOnlyQueryTool()
        self._query_tool.set_config(self.config)
        self.context.add_llm_tools(self._query_tool)

        self._detail_tool = BAOnlyEventDetailTool()
        self._detail_tool.set_config(self.config)
        self.context.add_llm_tools(self._detail_tool)
        logger.info("[BAOnly] 插件已初始化，LLM 工具已注册")

        # WebSocket 后台推送任务
        user_agent = self.config.get("user_agent", DEFAULT_USER_AGENT)
        self._notifier = StreamNotifier(context, self._store, self.config, user_agent)
        self._notifier.start()

    @filter.command("bao", alias="BAO")
    async def baonly_default(self, event: AstrMessageEvent):
        """截图 BAOnly 网页活动列表，默认每页 4 场"""
        yield event.plain_result("正在截图，页数：4，请稍后……")
        async for result in self._do_screenshot(event, 4):
            yield result

    @filter.command_group("baonly")
    async def baonly(self):
        pass

    @baonly.command("page")
    async def baonly_page(self, event: AstrMessageEvent, page_size: int = 4):
        """截图 BAOnly 网页活动列表，可指定每页显示数量(4/6/10/20/23/50) 如：baonly page 4"""
        if page_size not in VALID_PAGE_SIZES:
            sizes_str = ", ".join(map(str, VALID_PAGE_SIZES))
            yield event.plain_result(
                f"不支持的每页数量: {page_size}，可选值: {sizes_str}"
            )
            return
        yield event.plain_result(f"正在截图，页数：{page_size}，请稍后……")
        async for result in self._do_screenshot(event, page_size):
            yield result

    @baonly.command("query")
    async def baonly_query(self, event: AstrMessageEvent, status: str = "upcoming", city: str = ""):
        """查询 BAOnly 展会列表。用法：baonly query [status] [city]
        status 可选：upcoming/ongoing/past/all，city 如：深圳市"""
        token = self.config.get("token", "")
        user_agent = self.config.get("user_agent", DEFAULT_USER_AGENT)
        data = await fetch_events_list(
            token, user_agent, status=status, city=city
        )
        if "error" in data:
            yield event.plain_result(f"查询失败: {data['error']}")
            return

        events = data.get("events", [])
        if not events:
            yield event.plain_result(
                f"暂无符合条件的活动（查询: status={status}, city={city or '全部'}）。"
            )
            return

        lines = [f"共 {data.get('events_count', 0)} 场相关活动（查询: status={status}, city={city or '全部'}）："]
        for e in events[:10]:
            loc = f"{e.get('province') or ''} {e.get('city') or ''}".strip()
            lines.append(
                f"- [{e.get('state')}] {e.get('title')}\n"
                f"  时间: {e.get('timeLabel') or e.get('startAt') or '待定'}\n"
                f"  地点: {loc} {e.get('venueName') or ''}".rstrip() + "\n"
                f"  票价: {e.get('priceLabel') or '待定'} | 售票: {e.get('saleFlag') or '未知'}\n"
                f"  活动ID: {e.get('id')}"
            )
        yield event.plain_result("\n".join(lines))

    @baonly.command("detail")
    async def baonly_detail(self, event: AstrMessageEvent, event_id: str = ""):
        """查询单个 BAOnly 展会详情。用法：baonly detail <event_id>"""
        event_id = (event_id or "").strip()
        if not event_id:
            yield event.plain_result("请提供活动ID，例如：baonly detail abc123")
            return
        token = self.config.get("token", "")
        user_agent = self.config.get("user_agent", DEFAULT_USER_AGENT)
        data = await fetch_event_detail(token, user_agent, event_id)
        if data.get("not_found") or data.get("error"):
            yield event.plain_result(
                f"查询失败: {data.get('error', '未找到该活动')}"
            )
            return
        loc = f"{data.get('province') or ''} {data.get('city') or ''} {data.get('venueName') or ''}".strip()
        lines = [
            f"- {data.get('title')}",
            f"  时间: {data.get('timeLabel') or data.get('startAt') or '待定'}",
            f"  地点: {loc or '待定'} {data.get('address') or ''}".rstrip(),
            f"  票价: {data.get('priceLabel') or '待定'} | 售票: {data.get('saleFlag') or '未知'}",
        ]
        tickets = data.get("tickets") or []
        if tickets:
            lines.append("  票档:")
            for t in tickets[:6]:
                lines.append(f"    - {t.get('name') or '?'}：{t.get('priceLabel') or t.get('priceCents')}")
        if data.get("description"):
            lines.append(f"  简介: {data['description'][:200]}")
        if data.get("pcTicketUrl"):
            lines.append(f"  购票: {data['pcTicketUrl']}")
        yield event.plain_result("\n".join(lines))

    @baonly.command("sub", alias="subscribe")
    async def baonly_sub(self, event: AstrMessageEvent):
        """订阅当前会话，活动变更时自动推送。用法：baonly sub"""
        umo = event.unified_msg_origin
        is_group = bool(getattr(event.message_obj, "group_id", ""))
        channel_id = (
            str(event.message_obj.group_id) if is_group else event.get_sender_id()
        )
        display = await _resolve_display(self._group_cache, is_group, channel_id, "")
        await self._store.add(umo, is_group, channel_id, display)
        yield event.plain_result("已订阅当前会话，展会变更将自动推送。")

    @baonly.command("unsub", alias="unsubscribe")
    async def baonly_unsub(self, event: AstrMessageEvent):
        """取消订阅当前会话。用法：baonly unsub"""
        umo = event.unified_msg_origin
        removed = await self._store.remove(umo)
        yield event.plain_result(
            "已取消订阅当前会话。" if removed else "当前会话未在订阅列表中。"
        )

    @baonly.command("list")
    async def baonly_list(self, event: AstrMessageEvent):
        """查看当前全部订阅渠道。用法：baonly list"""
        subs = await self._store.list()
        if not subs:
            yield event.plain_result("当前没有订阅任何渠道。")
            return
        lines = [f"共 {len(subs)} 个订阅渠道："]
        for i, s in enumerate(subs, start=1):
            channel_id = s.get("channel_id", "") or extract_channel_id(s["umo"])
            if s.get("is_group"):
                name = await self._group_cache.get_group_name(channel_id) or s.get(
                    "display", ""
                )
                lines.append(f"{i}.群：{name}({channel_id})")
            else:
                nickname = await self._group_cache.get_user_nickname(channel_id) or s.get(
                    "display", ""
                )
                lines.append(f"{i}.私聊：{nickname}({channel_id})")
        lines.append("可使用 baonly sub/unsub 维护订阅渠道，也可在 WebUI 插件页管理。")
        yield event.plain_result("\n".join(lines))

    async def _do_screenshot(self, event: AstrMessageEvent, page_size: int):
        user_agent = self.config.get("user_agent", DEFAULT_USER_AGENT)

        output_dir = os.path.abspath(os.path.join("data", "temp", PLUGIN_NAME))
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(
            output_dir, f"baonly_page{page_size}_{int(time.time())}.png"
        )

        extra_wait = self.config.get("extra_wait_seconds", 0)
        if extra_wait > 0:
            logger.info(f"[BAOnly] 额外等待 {extra_wait} 秒...")
            await asyncio.sleep(extra_wait)

        try:
            await capture_screenshot(
                page_size=page_size,
                output_path=output_path,
                user_agent=user_agent,
                astrbot_version=self._astrbot_version,
                plugin_name=PLUGIN_NAME,
                plugin_version=self._plugin_version,
                proxy_host=self.config.get("proxy_host", ""),
                proxy_port=self.config.get("proxy_port", ""),
                proxy_username=self.config.get("proxy_username", ""),
                proxy_password=self.config.get("proxy_password", ""),
            )
            yield event.image_result(output_path)
        except Exception as e:
            logger.error(f"[BAOnly] 截图失败: {e}", exc_info=True)
            yield event.plain_result(f"截图失败: {str(e)}")

    async def terminate(self):
        """插件卸载/停用时调用"""
        self._notifier.stop()
        logger.info("[BAOnly] 插件已卸载")
