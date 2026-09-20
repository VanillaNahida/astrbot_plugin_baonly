import asyncio
import json
import random
import time
from datetime import datetime
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import MessageChain
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .subscriptions import SubscriptionStore
from .tools.baonly_query import fetch_events_list, DEFAULT_USER_AGENT
from .tools.baonly_detail import fetch_event_detail, _map_event_detail

PLUGIN_NAME = "astrbot_plugin_baonly"
STREAM_URL = "wss://beta.baonly.cn/api/public/stream"

# 活动缓存文件：data/plugin_data/{plugin_name}/activities_cache.json
_ACTIVITIES_CACHE_FILE = (
    Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME / "activities_cache.json"
)

# 参与“更新”对比的字段
_TRACKED_FIELDS = (
    "title",
    "timeLabel",
    "priceLabel",
    "saleFlag",
    "province",
    "city",
    "venueName",
)


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _format_duration(seconds: float) -> str:
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}小时{m}分{s}秒"
    if m:
        return f"{m}分{s}秒"
    return f"{s}秒"


def _summarize(data: dict) -> dict:
    """从列表项/详情中提取用于对比与推送的摘要字段。"""
    return {
        "title": data.get("title") or "",
        "timeLabel": data.get("timeLabel") or "",
        "priceLabel": data.get("priceLabel") or "",
        "saleFlag": data.get("saleFlag") or "",
        "province": data.get("province") or "",
        "city": data.get("city") or "",
        "venueName": data.get("venueName") or "",
        "pcTicketUrl": data.get("pcTicketUrl") or "",
    }


def _has_tracked_change(old_s: dict, new_s: dict) -> bool:
    return any(old_s.get(k) != new_s.get(k) for k in _TRACKED_FIELDS)


def _format_event_text(event_id: str, action: str, info: dict) -> str:
    """把一次变更组装成推送文本。action: 新增 / 移除 / 更新。"""
    title = info.get("title") or "（无标题）"
    lines = [f"[BAOnly活动{action}] {title}"]

    time_label = info.get("timeLabel") or ""
    if time_label:
        lines.append(f"时间：{time_label}")

    province = info.get("province") or ""
    city = info.get("city") or ""
    if province:
        lines.append(f"地点：{province}" + (f"·{city}" if city else ""))
    elif city:
        lines.append(f"地点：{city}")

    venue = info.get("venueName") or ""
    if venue:
        lines.append(f"场馆：{venue}")

    price = info.get("priceLabel") or ""
    if price:
        lines.append(f"票价：{price}")

    link = info.get("pcTicketUrl") or ""
    if link:
        lines.append(f"详情：{link}")
    else:
        lines.append(f"活动ID：{event_id}")

    return "\n".join(lines)


class ActivityCache:
    """最近一次拉取到的活动清单缓存，用于对比新增/移除/更新。"""

    def __init__(self, path: Path):
        self._path = path
        self._lock = asyncio.Lock()

    async def load(self):
        async with self._lock:
            try:
                if self._path.exists():
                    data = json.loads(self._path.read_text(encoding="utf-8"))
                    events = data.get("events", {})
                    if isinstance(events, dict):
                        return {
                            str(k): v for k, v in events.items() if isinstance(v, dict)
                        }
            except Exception as e:
                logger.warning(f"[BAOnly] 读取活动缓存失败: {e}")
            return None

    async def save(self, events: dict):
        async with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                payload = {"updatedAt": _now_text(), "events": events}
                self._path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception as e:
                logger.warning(f"[BAOnly] 写入活动缓存失败: {e}")


class StreamNotifier:
    """WebSocket 长连接订阅 beta.baonly.cn 变更推送。

    收到活动变更指纹后拉取最新活动列表，与本地缓存对比，推送“新增 / 移除 / 更新”。
    断线、维护模式、API Key 停用等情况会记录状态，可用 /baonly status 查看。
    """

    def __init__(self, context, store: SubscriptionStore, config, user_agent: str):
        self._context = context
        self._store = store
        self._config = config
        self._user_agent = user_agent
        # 推送基础延时(秒)；每次推送额外叠加 0.5~1s 随机抖动，降低风控风险
        self._push_delay_base = float(config.get("push_delay_seconds", 0))
        self._cache = ActivityCache(_ACTIVITIES_CACHE_FILE)

        self._task = None
        self._sync_task = None
        self._stopping = False
        self._sync_event = asyncio.Event()
        self._sync_lock = asyncio.Lock()

        # 连接状态（供 /baonly status 读取）
        self._connected = False
        self._connected_at = None
        self._last_session_duration = None
        self._last_disconnect = None  # (时间, 原因)
        self._scopes = []
        self._api_key_valid = None  # None=未知, True=有效, False=无效/已停用
        self._maintenance = False
        self._pending_close = None
        self._closing = False
        self._push_count = 0
        self._last_push_at = None

    def start(self):
        if self._task is None or self._task.done():
            loop = asyncio.get_event_loop()
            self._task = loop.create_task(self._run())
            self._sync_task = loop.create_task(self._sync_loop())
            logger.info("[BAOnly] WebSocket 推送任务已启动")

    def stop(self):
        self._stopping = True
        if self._task and not self._task.done():
            self._task.cancel()
        if self._sync_task and not self._sync_task.done():
            self._sync_task.cancel()

    def _schedule_sync(self):
        self._sync_event.set()

    # ---------- 状态 ----------

    def describe_status(self) -> list[str]:
        lines = []
        token = self._config.get("token", "")
        if not token:
            lines.append("WebSocket 推送：未配置 API Key（token）")
            lines.append("提示：请在插件配置中填写 token 后重启插件。")
            return lines

        if self._connected:
            dur = (
                _format_duration(time.time() - self._connected_at)
                if self._connected_at
                else "未知"
            )
            lines.append(f"WebSocket 推送：已连接（已连接 {dur}）")
        elif self._task and not self._task.done():
            lines.append("WebSocket 推送：未连接，自动重连中……")
        else:
            lines.append("WebSocket 推送：未连接")

        if self._api_key_valid is True:
            lines.append("API Key：有效")
        elif self._api_key_valid is False:
            lines.append("API Key：无效或已停用（请检查插件配置中的 token）")
        else:
            lines.append("API Key：未知（等待首次连接确认）")

        if self._maintenance:
            lines.append("站点状态：维护模式中（维护结束后会自动恢复连接）")

        if self._scopes:
            lines.append("推送权限：" + "、".join(self._scopes))
        else:
            lines.append("推送权限：未知")

        if self._last_disconnect:
            when, reason = self._last_disconnect
            lines.append(f"最近断开：{when}（{reason}）")

        if self._push_count:
            extra = f"，最近于 {self._last_push_at}" if self._last_push_at else ""
            lines.append(f"累计推送：{self._push_count} 次{extra}")
        else:
            lines.append("累计推送：0 次")
        return lines

    def _record_disconnect(self, reason: str):
        self._last_disconnect = (_now_text(), reason)

    # ---------- 连接 ----------

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
                self._record_disconnect(f"{type(e).__name__}: {e}")
                logger.warning(f"[BAOnly] WebSocket 连接中断: {e}")
            if self._stopping:
                break
            logger.info(f"[BAOnly] {reconnect_interval} 秒后重连 WebSocket...")
            await asyncio.sleep(reconnect_interval)

    async def _connect_once(self, token: str, ping_interval: int):
        from websockets.asyncio.client import connect
        from websockets.exceptions import InvalidStatus

        logger.info(f"[BAOnly] 连接 WebSocket: {STREAM_URL}")
        try:
            async with connect(
                STREAM_URL,
                additional_headers={"x-api-key": token, "User-Agent": self._user_agent},
                ping_interval=ping_interval,
                ping_timeout=ping_interval,
                open_timeout=15,
            ) as websocket:
                logger.info("[BAOnly] WebSocket 已连接")
                self._connected = True
                self._connected_at = time.time()
                self._maintenance = False
                async for raw in websocket:
                    if self._stopping:
                        break
                    if not raw:
                        continue
                    text = (
                        raw
                        if isinstance(raw, str)
                        else raw.decode("utf-8", errors="ignore")
                    )
                    try:
                        await self._handle_message(text)
                    except Exception as e:
                        logger.warning(f"[BAOnly] 处理推送消息失败: {e}")
                    if self._closing:
                        break
                code = websocket.close_code
                reason = (websocket.close_reason or "").strip() or "连接已关闭"
                self._mark_disconnected(code, reason)
        except InvalidStatus as e:
            status = getattr(e, "response", None)
            code = getattr(status, "status_code", None)
            if code == 401:
                self._api_key_valid = False
                reason = "API Key 无效或已停用（HTTP 401）"
                logger.error(f"[BAOnly] {reason}，请在插件配置中检查 token")
            elif code == 403:
                reason = "API Key 没有推送权限（HTTP 403）"
                logger.error(f"[BAOnly] {reason}")
            else:
                reason = f"WebSocket 握手失败（HTTP {code or '未知'}）"
                logger.error(f"[BAOnly] {reason}")
            self._record_disconnect(reason)
            raise

    def _mark_disconnected(self, code, reason: str):
        if self._connected and self._connected_at:
            self._last_session_duration = time.time() - self._connected_at
        self._connected = False
        self._connected_at = None
        self._closing = False

        # 优先使用服务端 closing 消息里的 code/reason
        pending = self._pending_close
        self._pending_close = None
        if pending:
            if code is None or code in (1000, 1001, 1006):
                code = pending.get("code")
            if pending.get("reason"):
                reason = pending["reason"]

        if code == 4401:
            self._api_key_valid = False
            reason = reason or "API Key 无效或已停用"
            logger.error(f"[BAOnly] WebSocket 断开：{reason}")
        elif code == 4403:
            self._api_key_valid = True
            reason = reason or "API Key 没有推送权限"
            logger.warning(f"[BAOnly] WebSocket 断开：{reason}")
        elif code == 4429:
            self._api_key_valid = True
            reason = reason or "同一 Key 的连接数超限"
            logger.warning(f"[BAOnly] WebSocket 断开：{reason}")
        elif code == 4503:
            self._api_key_valid = True
            self._maintenance = True
            reason = reason or "站点进入维护模式"
            logger.warning(
                f"[BAOnly] WebSocket 断开：{reason}，维护结束后将自动重连"
            )
        elif code not in (None, 1000, 1001, 1006):
            logger.warning(
                f"[BAOnly] WebSocket 断开：{reason or '连接关闭'}（关闭码 {code}）"
            )
        else:
            logger.info(f"[BAOnly] WebSocket 断开：{reason or '连接关闭'}")

        self._record_disconnect(reason)

    # ---------- 消息处理 ----------

    async def _handle_message(self, text: str):
        try:
            msg = json.loads(text)
        except Exception:
            logger.warning(f"[BAOnly] 推送消息解析失败: {text[:200]}")
            return
        if not isinstance(msg, dict):
            return

        mtype = msg.get("type") or ""
        event_id = msg.get("eventId") or msg.get("event_id")

        if mtype == "ready":
            scopes = msg.get("scopes", [])
            self._scopes = scopes if isinstance(scopes, list) else []
            self._api_key_valid = True
            logger.info(f"[BAOnly] 流已就绪，权限: {self._scopes}")
            # 重连后与缓存对齐，补齐断线期间漏掉的变更
            self._schedule_sync()
            return

        if mtype == "closing":
            code = msg.get("code")
            reason = str(msg.get("reason") or "服务端主动断开")
            self._pending_close = {"code": code, "reason": reason}
            self._closing = True
            if code == 4503:
                self._maintenance = True
                self._api_key_valid = True
                logger.warning(
                    f"[BAOnly] 站点进入维护模式，连接即将断开：{reason}"
                )
            elif code == 4401:
                self._api_key_valid = False
                logger.error(
                    f"[BAOnly] API Key 无效或已停用，连接即将断开：{reason}"
                )
            elif code == 4403:
                self._api_key_valid = True
                logger.warning(
                    f"[BAOnly] 当前 API Key 没有任何推送权限：{reason}"
                )
            elif code == 4429:
                self._api_key_valid = True
                logger.warning(
                    f"[BAOnly] 同一 Key 的连接数超限，连接即将断开：{reason}"
                )
            else:
                logger.warning(
                    f"[BAOnly] 服务端主动断开（code={code}）：{reason}"
                )
            return

        is_event_change = bool(event_id) or str(mtype).startswith("event")
        if not is_event_change:
            # 非活动类推送（公告/维护等），只记录
            logger.info(f"[BAOnly] 收到推送: {text[:200]}")
            return

        # 活动变更：触发一次列表对比（多条短时间变更会合并）
        self._schedule_sync()

    # ---------- 对比与推送 ----------

    async def _sync_loop(self):
        while not self._stopping:
            await self._sync_event.wait()
            if self._stopping:
                break
            self._sync_event.clear()
            try:
                await self._sync_and_push()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[BAOnly] 活动对比推送失败: {e}")

    async def _sync_and_push(self):
        async with self._sync_lock:
            token = self._config.get("token", "")
            try:
                new_events = await self._fetch_all_events(token)
            except Exception as e:
                logger.warning(f"[BAOnly] 拉取活动列表失败，跳过本次对比: {e}")
                return
            if not new_events:
                logger.warning("[BAOnly] 活动列表为空，跳过本次对比")
                return

            new = {eid: _summarize(ev) for eid, ev in new_events.items()}
            old = await self._cache.load()

            if old is None:
                # 首次运行 / 缓存缺失：只建立基线，不推送
                await self._cache.save(new)
                logger.info(f"[BAOnly] 已建立活动基线（{len(new)} 场），本次不推送")
                return

            added_ids = [eid for eid in new if eid not in old]
            removed_ids = [eid for eid in old if eid not in new]
            updated_ids = [
                eid
                for eid in new
                if eid in old and _has_tracked_change(old[eid], new[eid])
            ]

            if not (added_ids or removed_ids or updated_ids):
                logger.info("[BAOnly] 活动无变化，跳过推送")
                return

            subs = await self._store.list()
            if not subs:
                logger.info("[BAOnly] 无订阅渠道，仅更新活动缓存")
                await self._cache.save(new)
                return

            # 组装推送内容（新增/更新尽量补全详情）
            messages: list[tuple[str, str]] = []
            for eid in added_ids:
                detail = await self._fetch_detail_safe(eid)
                if detail:
                    new[eid] = _summarize(detail)
                    messages.append(("新增", _format_event_text(eid, "新增", detail)))
                else:
                    messages.append(("新增", _format_event_text(eid, "新增", new[eid])))
            for eid in removed_ids:
                messages.append(("移除", _format_event_text(eid, "移除", old[eid])))
            for eid in updated_ids:
                detail = await self._fetch_detail_safe(eid)
                if detail:
                    new[eid] = _summarize(detail)
                    messages.append(("更新", _format_event_text(eid, "更新", detail)))
                else:
                    messages.append(("更新", _format_event_text(eid, "更新", new[eid])))

            await self._cache.save(new)

            for label, text_content in messages:
                logger.info(
                    f"[BAOnly] 推送变更[{label}]，共 {len(subs)} 个订阅渠道"
                )
                await self._push_to_all(text_content)

    async def _fetch_all_events(self, token: str) -> dict:
        page = 1
        page_size = 200
        events: dict = {}
        while True:
            data = await fetch_events_list(
                token,
                self._user_agent,
                status="all",
                include_past=True,
                page=page,
                page_size=page_size,
            )
            if "error" in data:
                raise RuntimeError(data["error"])
            for e in data.get("events", []):
                eid = str(e.get("id") or "").strip()
                if eid:
                    events[eid] = e
            page_count = data.get("pageCount") or 0
            page_num = data.get("page") or page
            if page_num >= page_count or not data.get("events"):
                break
            page = page_num + 1
        return events

    async def _fetch_detail_safe(self, event_id: str):
        try:
            data = await fetch_event_detail(
                self._config.get("token", ""), self._user_agent, event_id
            )
            if data.get("not_found") or data.get("error"):
                return None
            return _map_event_detail(data)
        except Exception as e:
            logger.warning(f"[BAOnly] 获取活动详情失败 {event_id}: {e}")
            return None

    async def _push_to_all(self, text_content: str):
        subs = await self._store.list()
        if not subs:
            return
        chain = MessageChain().message(text_content)
        for sub in subs:
            # 按配置基础延时 + 随机 0.5~1s 抖动，错开推送降低风控风险
            delay = self._push_delay_base + random.uniform(0.5, 1.0)
            await asyncio.sleep(delay)
            try:
                ok = await self._context.send_message(sub["umo"], chain)
                if ok:
                    self._push_count += 1
                    self._last_push_at = _now_text()
                    logger.info(f"[BAOnly] 已推送到: {sub['display'] or sub['umo']}")
                else:
                    logger.warning(
                        f"[BAOnly] 推送目标不可达: {sub['display'] or sub['umo']}"
                        f"（{sub['umo']}）"
                    )
            except Exception as e:
                logger.warning(f"[BAOnly] 推送失败 {sub['umo']}: {e}")
