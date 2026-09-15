import asyncio
import json
import random

from astrbot.api import logger
from astrbot.api.event import MessageChain

from .subscriptions import SubscriptionStore
from .tools.baonly_detail import fetch_event_detail, _map_event_detail

STREAM_URL = "wss://beta.baonly.cn/api/public/stream"


def _build_change_text(event_id: str, action: str, detail: dict) -> str:
    """把一次变更组装成推送文本。"""
    title = detail.get("title") or "（无标题）"
    time_label = detail.get("timeLabel") or ""
    city = detail.get("city") or ""
    province = detail.get("province") or ""
    venue = detail.get("venueName") or detail.get("address") or ""
    price_label = detail.get("priceLabel") or ""
    link = detail.get("pcTicketUrl") or ""

    lines = []

    action_word = {
        "created": "新增",
        "updated": "更新",
        "deleted": "下架/删除",
    }.get(action, "变更")

    lines.append(f"[BAOnly活动{action_word}] {title}")
    if time_label:
        lines.append(f"时间：{time_label}")
    if province:
        lines.append(f"地点：{province}" + (f"·{city}" if city else ""))
    if venue:
        lines.append(f"场馆：{venue}")
    if price_label:
        lines.append(f"票价：{price_label}")
    if link:
        lines.append(f"详情：{link}")
    else:
        lines.append(f"活动ID：{event_id}")

    return "\n".join(lines)


class StreamNotifier:
    """WebSocket 长连接订阅 beta.baonly.cn 变更推送。

    收到变更指纹( eventId )后主动调 REST 补全内容，并按订阅配置推送。
    """

    def __init__(
        self,
        context,
        store: SubscriptionStore,
        config,
        user_agent: str,
    ):
        self._context = context
        self._store = store
        self._config = config
        self._user_agent = user_agent
        # 推送基础延时(秒)；每次推送额外叠加 0.5~1s 随机抖动，降低风控风险
        self._push_delay_base = float(config.get("push_delay_seconds", 0))
        self._task = None
        self._stopping = False

    def start(self):
        if self._task is None or self._task.done():
            self._task = asyncio.get_event_loop().create_task(self._run())
            logger.info("[BAOnly] WebSocket 推送任务已启动")

    def stop(self):
        self._stopping = True
        if self._task and not self._task.done():
            self._task.cancel()

    async def _run(self):
        ping_interval = int(self._config.get("ws_ping_interval", 30))
        reconnect_interval = int(self._config.get("ws_reconnect_interval", 30))
        token = self._config.get("token", "")

        if not token:
            logger.warning("[BAOnly] 未配置 token，跳过 WebSocket 订阅")
            return

        while not self._stopping:
            try:
                await self._connect_once(token, ping_interval)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[BAOnly] WebSocket 连接中断: {e}")
            if self._stopping:
                break
            logger.info(f"[BAOnly] {reconnect_interval} 秒后重连 WebSocket...")
            await asyncio.sleep(reconnect_interval)

    async def _connect_once(self, token: str, ping_interval: int):
        from websockets.asyncio.client import connect

        logger.info(f"[BAOnly] 连接 WebSocket: {STREAM_URL}")
        async with connect(
            STREAM_URL,
            additional_headers={"x-api-key": token, "User-Agent": self._user_agent},
            ping_interval=ping_interval,
            ping_timeout=ping_interval,
        ) as websocket:
            logger.info("[BAOnly] WebSocket 已连接")
            async for raw in websocket:
                if self._stopping:
                    break
                if not raw:
                    continue
                text = raw if isinstance(raw, str) else raw.decode("utf-8", errors="ignore")
                try:
                    await self._handle_message(text)
                except Exception as e:
                    logger.warning(f"[BAOnly] 处理推送消息失败: {e}")

    async def _handle_message(self, text: str):
        msg = json.loads(text)

        # 初始 ready：说明实际拿到的推送权限
        if isinstance(msg, dict) and msg.get("type") == "ready":
            scopes = msg.get("scopes", [])
            logger.info(f"[BAOnly] 流已就绪，权限: {scopes}")
            return

        event_id = None
        action = "updated"

        if isinstance(msg, dict):
            event_id = msg.get("eventId") or msg.get("event_id")
            action = msg.get("action") or msg.get("type") or "updated"

        if not event_id:
            # 非活动类推送（公告/维护等），只记录
            logger.info(f"[BAOnly] 收到推送: {text[:200]}")
            return

        detail = await fetch_event_detail(
            self._config.get("token", ""), self._user_agent, event_id
        )
        if detail.get("not_found") or detail.get("error"):
            action = "deleted"
            detail = {}
            # 已删除时用本地对照表的名称兜底
            from .event_name_map import event_name

            cached = await event_name(event_id)
            if cached:
                detail["title"] = cached
        else:
            detail = _map_event_detail(detail)

        text_content = _build_change_text(event_id, action, detail)

        subs = await self._store.list()
        if not subs:
            logger.info("[BAOnly] 无订阅渠道，跳过推送")
            return

        chain = MessageChain().message(text_content)
        for sub in subs:
            # 按配置基础延时 + 随机 0.5~1s 抖动，错开推送降低风控风险
            delay = self._push_delay_base + random.uniform(0.5, 1.0)
            await asyncio.sleep(delay)
            try:
                await self._context.send_message(sub["umo"], chain)
                logger.info(f"[BAOnly] 已推送到: {sub['display'] or sub['umo']}")
            except Exception as e:
                logger.warning(f"[BAOnly] 推送失败 {sub['umo']}: {e}")
