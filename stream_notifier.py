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
from .time_utils import format_time_range
from .tools.baonly_query import fetch_events_list, DEFAULT_USER_AGENT
from .tools.baonly_detail import fetch_event_detail, _map_event_detail

PLUGIN_NAME = "astrbot_plugin_baonly"
STREAM_URL = "wss://www.baonly.cn/api/public/stream"

# 活动缓存文件：data/plugin_data/{plugin_name}/activities_cache.json
_ACTIVITIES_CACHE_FILE = (
    Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME / "activities_cache.json"
)

# 参与“更新”对比的字段
# 时间用由 startAt / endAt 推导出的标准时间文案（timeText）对比，
# 而不是源站原始文案 timeLabel —— 后者可能只是「预计时间」之类的占位文字。
_TRACKED_FIELDS = (
    "title",
    "timeText",
    "priceLabel",
    "saleFlag",
    "province",
    "city",
    "venueName",
    "markers",
    "featured",
)

# 运营标记（markers）中文文案
_MARKER_LABELS = {
    "cancelled": "已取消",
    "postponed": "已延期",
    "venueChanged": "地点变更",
}

# Diff 展示字段：展示标签 -> 参与对比的摘要字段（多字段会拼成一行，如 省·市）
_DIFF_FIELDS = (
    ("标题", ("title",)),
    ("时间", ("timeText",)),
    ("地点", ("province", "city")),
    ("场馆", ("venueName",)),
    ("票价", ("priceLabel",)),
    ("售票", ("saleFlag",)),
    ("标记", ("markers",)),
    ("精选", ("featured",)),
)


# WS 消息类型 -> 推送动作
_ACTION_BY_TYPE = {
    "event.created": "新增",
    "event.updated": "更新",
    "event.removed": "移除",
}


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _time_text(summary: dict) -> str:
    """时间展示值：标准时间优先，兼容只存了原始文案的旧缓存。"""
    text = str(summary.get("timeText") or "").strip()
    if text:
        return text
    if not any(k in summary for k in ("startAt", "endAt", "timeLabel")):
        return ""
    return format_time_range(
        summary.get("startAt"), summary.get("endAt"), summary.get("timeLabel")
    )


def _summary_value(summary: dict, keys: tuple) -> str:
    """把摘要里的一个或多个字段拼成展示用的值，空值返回空串。"""
    if keys == ("featured",):
        return "是" if summary.get("featured") else ""
    if keys == ("timeText",):
        return _time_text(summary)
    parts = [str(summary.get(k) or "").strip() for k in keys]
    return "·".join(p for p in parts if p)


def _diff_rows(old: dict, new: dict) -> list:
    """对比两份摘要，返回发生变化的字段：(标签, 旧值, 新值)。"""
    rows = []
    for label, keys in _DIFF_FIELDS:
        # 旧缓存里缺字段时不参与对比，避免插件升级后误报变更
        if any(k not in old for k in keys):
            continue
        old_value = _summary_value(old, keys)
        new_value = _summary_value(new, keys)
        if old_value != new_value:
            rows.append((label, old_value, new_value))
    return rows


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
    start_at = data.get("startAt")
    end_at = data.get("endAt")
    time_label = data.get("timeLabel")
    return {
        "title": data.get("title") or "",
        # 标准时间（startAt/endAt）与由它推导出的展示文案
        "startAt": start_at or "",
        "endAt": end_at or "",
        "timeLabel": time_label or "",
        "timeText": format_time_range(start_at, end_at, time_label),
        "priceLabel": data.get("priceLabel") or "",
        "saleFlag": data.get("saleFlag") or "",
        "province": data.get("province") or "",
        "city": data.get("city") or "",
        "venueName": data.get("venueName") or "",
        "markers": _marker_labels(data.get("markers")),
        "featured": "1" if data.get("featured") else "",
        "pcTicketUrl": data.get("pcTicketUrl") or "",
    }


def _marker_labels(value) -> str:
    """把 markers 转成中文文案；兼容列表与已拼接的字符串。"""
    if not value:
        return ""
    items = value if isinstance(value, (list, tuple)) else str(value).split("、")
    return "、".join(_MARKER_LABELS.get(str(m), str(m)) for m in items if m)


def _has_tracked_change(old_s: dict, new_s: dict) -> bool:
    for key in _TRACKED_FIELDS:
        # 旧缓存里没有该字段时不参与对比，避免插件升级后误报变更
        if key not in old_s:
            continue
        if old_s.get(key) != new_s.get(key):
            return True
    return False


def _format_event_text(
    event_id: str, action: str, old: dict = None, new: dict = None, note: str = ""
) -> str:
    """组装推送文本。

    更新：Git Diff 风格，逐字段输出 ``--- 旧值`` 与 ``+++ 新值``；
    新增 / 移除：按普通字段列表输出（不使用 Git Diff 记号）。

    尾部依次为活动链接（有则输出）、活动 ID 与 WS 备注。
    """
    old = old or {}
    new = new or {}
    source = old if action == "移除" else new
    title = new.get("title") or old.get("title") or "（无标题）"
    lines = [f"[BAOnly活动{action}] {title}"]

    if action == "更新":
        for label, old_value, new_value in _diff_rows(old, new):
            lines.append(f"--- {label}：{old_value or '（无）'}")
            lines.append(f"+++ {label}：{new_value or '（无）'}")
    else:
        for label, keys in _DIFF_FIELDS:
            # 标题已在首行，不再重复
            if label == "标题":
                continue
            value = _summary_value(source, keys)
            if value:
                lines.append(f"{label}：{value}")

    link = new.get("pcTicketUrl") or old.get("pcTicketUrl") or ""
    if link:
        lines.append(f"详情：{link}")
    if event_id:
        lines.append(f"活动ID：{event_id}")
    if note:
        lines.append(f"备注：{note}")
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
    """WebSocket 长连接订阅 www.baonly.cn 变更推送。

    推送消息自带 eventId（合并消息为 eventIds 数组）与 note 备注，因此只按 ID 拉取
    ``GET /api/public/events/{eventId}`` 并与本地缓存对比，推送「新增 / 移除 / 更新」；
    只有 WS 下发的活动才会推送，重连（ready）时的全量对齐只刷新缓存基线、不推送。
    断线、维护模式、API Key 停用等情况会记录状态，可用 /baonly status 查看。
    """

    def __init__(self, context, store: SubscriptionStore, config, user_agent: str):
        self._context = context
        self._store = store
        self._config = config
        self._user_agent = user_agent
        # 推送基础延时(秒)；每次推送额外叠加 0.5~1s 随机抖动，降低风控风险
        self._push_delay_base = float(config.get("push_delay_seconds", 0))
        # 测试开关：开启后活动变更只推私聊，不推群聊
        self._disable_group_push = bool(config.get("disable_group_push", False))
        self._cache = ActivityCache(_ACTIVITIES_CACHE_FILE)

        self._task = None
        self._sync_task = None
        self._stopping = False
        self._sync_event = asyncio.Event()
        self._sync_lock = asyncio.Lock()
        # 待对比的活动：event_id -> {"action": WS 给出的动作, "note": WS 备注}
        self._pending: dict[str, dict] = {}
        # 为 True 表示需要一次静默的缓存对齐（重连 / 缺少基线）
        self._pending_full = False

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

    def _schedule_sync(self, event_ids=None, action: str = "", note: str = ""):
        """安排一次对比。

        带 event_ids（WS 下发）时只对比这些活动，并记录 WS 给出的动作与备注；
        否则只做一次静默的缓存对齐，不推送。
        """
        ids = {str(i) for i in (event_ids or []) if i}
        if not ids:
            self._pending_full = True
            self._sync_event.set()
            return
        for eid in ids:
            meta = self._pending.setdefault(eid, {"action": "", "note": ""})
            meta["action"] = action or meta["action"]
            meta["note"] = note or meta["note"]
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

        mtype = str(msg.get("type") or "")
        event_id = msg.get("eventId") or msg.get("event_id")
        event_ids = msg.get("eventIds") or msg.get("event_ids")

        if mtype == "ready":
            scopes = msg.get("scopes", [])
            self._scopes = scopes if isinstance(scopes, list) else []
            self._api_key_valid = True
            logger.info(f"[BAOnly] 流已就绪，权限: {self._scopes}")
            # 重连后与缓存对齐（只刷新缓存，不推送）
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

        # 活动变更：只对比 WS 下发的这些活动，按消息类型确定动作
        ids = []
        if isinstance(event_ids, (list, tuple)):
            ids = [str(i) for i in event_ids if i]
        elif event_id:
            ids = [str(event_id)]

        if ids:
            action = _ACTION_BY_TYPE.get(mtype, "")
            note = str(msg.get("note") or "").strip()
            logger.info(
                f"[BAOnly] 收到活动变更推送（{mtype or 'event'}，{len(ids)} 场"
                f"{'，备注：' + note if note else ''}）: {text[:200]}"
            )
            self._schedule_sync(ids, action, note)
            return

        if mtype.startswith("event"):
            # 没带活动 ID 的变更消息：只对齐缓存，不推送
            logger.info(f"[BAOnly] 推送未含活动 ID，仅对齐缓存: {text[:200]}")
            self._schedule_sync()
            return

        # 非活动类推送（公告/维护等），只记录
        logger.info(f"[BAOnly] 收到推送: {text[:200]}")

    # ---------- 对比与推送 ----------

    async def _sync_loop(self):
        while not self._stopping:
            await self._sync_event.wait()
            if self._stopping:
                break
            self._sync_event.clear()
            full = self._pending_full
            pending = self._pending
            self._pending_full = False
            self._pending = {}
            if not full and not pending:
                continue
            try:
                await self._sync_once(full, pending)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[BAOnly] 活动对比推送失败: {e}")

    async def _sync_once(self, full: bool, pending: dict):
        async with self._sync_lock:
            old = await self._cache.load()
            if full or old is None:
                # 重连对齐 / 首次运行：静默刷新缓存，不推送
                old = await self._align_all(old)
                if not pending:
                    return
            await self._sync_events(pending, old)

    async def _align_all(self, old: dict | None) -> dict:
        """全量拉取列表刷新缓存基线。

        推送只针对 WS 下发的活动，因此对齐结果只写入缓存、不产生推送。
        """
        token = self._config.get("token", "")
        try:
            new_events = await self._fetch_all_events(token)
        except Exception as e:
            logger.warning(f"[BAOnly] 拉取活动列表失败，跳过本次对齐: {e}")
            return old or {}
        if not new_events:
            logger.warning("[BAOnly] 活动列表为空，跳过本次对齐")
            return old or {}

        new = {eid: _summarize(ev) for eid, ev in new_events.items()}
        await self._cache.save(new)

        if old is None:
            logger.info(f"[BAOnly] 已建立活动基线（{len(new)} 场）")
            return new

        changed = sum(
            1
            for eid, summary in new.items()
            if eid not in old or _has_tracked_change(old[eid], summary)
        ) + sum(1 for eid in old if eid not in new)
        logger.info(
            f"[BAOnly] 活动缓存已对齐（{len(new)} 场，其中 {changed} 场与缓存不同），"
            f"本次不推送（仅推送 WS 下发的活动变更）"
        )
        return new

    async def _sync_events(self, pending: dict, old: dict):
        """增量对比：只处理 WS 下发的活动，按 ID 拉取详情并与缓存比对。"""
        new = dict(old)
        messages: list[tuple[str, str]] = []
        skipped = 0
        for eid, meta in sorted(pending.items()):
            action = str(meta.get("action") or "")
            note = str(meta.get("note") or "")

            status, detail = await self._fetch_detail(eid)
            if status == "error":
                # 拉取失败不推送，避免文案不完整 / 误报移除
                skipped += 1
                continue

            prev = old.get(eid)
            summary = _summarize(detail) if status == "ok" else None

            if action == "移除" or status == "gone":
                source = prev or summary
                if source is None:
                    continue
                new.pop(eid, None)
                messages.append(
                    ("移除", _format_event_text(eid, "移除", source, None, note))
                )
                continue

            if action == "新增" or prev is None:
                new[eid] = summary
                messages.append(
                    ("新增", _format_event_text(eid, "新增", None, summary, note))
                )
                continue

            if action or _has_tracked_change(prev, summary):
                # WS 明确说明是更新时直接推送，即使本地比对无差异
                new[eid] = summary
                messages.append(
                    ("更新", _format_event_text(eid, "更新", prev, summary, note))
                )
                continue

            # bulk 合并消息且本地比对无差异：视为无需推送
            skipped += 1

        if not messages:
            logger.info(
                f"[BAOnly] 活动无变化，跳过推送（WS 下发 {len(pending)} 场，"
                f"其中 {skipped} 场跳过）"
            )
            return

        await self._cache.save(new)
        await self._push_messages(messages)

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

    async def _fetch_detail(self, event_id: str):
        """按 ID 拉取单个活动详情，返回 (状态, 详情)。

        状态：``ok`` 拉取成功 / ``gone`` 活动已下架或删除 / ``error`` 拉取失败。
        """
        try:
            data = await fetch_event_detail(
                self._config.get("token", ""), self._user_agent, event_id
            )
        except Exception as e:
            logger.warning(f"[BAOnly] 获取活动详情失败 {event_id}: {e}")
            return "error", None
        if data.get("not_found"):
            return "gone", None
        if data.get("error"):
            logger.warning(f"[BAOnly] 获取活动详情失败 {event_id}: {data['error']}")
            return "error", None
        return "ok", _map_event_detail(data)

    def _target_subs(self, subs: list) -> list:
        """按「关闭群发」测试开关过滤推送目标：开启后只保留私聊渠道。"""
        if not self._disable_group_push:
            return list(subs)
        group_count = sum(1 for s in subs if s.get("is_group"))
        targets = [s for s in subs if not s.get("is_group")]
        logger.info(
            f"[BAOnly] 已开启「关闭群发」（仅供测试使用），"
            f"跳过 {group_count} 个群聊渠道，仅推送 {len(targets)} 个私聊渠道"
        )
        return targets

    async def _push_messages(self, messages: list):
        """把组装好的变更文案推送到全部订阅渠道。"""
        if not messages:
            return
        subs = self._target_subs(await self._store.list())
        if not subs:
            logger.info("[BAOnly] 无可用推送渠道，仅更新活动缓存")
            return
        for label, text_content in messages:
            logger.info(f"[BAOnly] 推送变更[{label}]，共 {len(subs)} 个订阅渠道")
            await self._push_to_all(text_content, subs)

    async def _push_to_all(self, text_content: str, subs: list):
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
