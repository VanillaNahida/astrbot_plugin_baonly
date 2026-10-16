from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace

from ...utils.log import log
from ..api import ApiError, EventNotFound
from ..api.mapping import map_list_item
from ..events import EventCatalog
from .broadcaster import Broadcaster
from .cache import SnapshotCache
from .protocol import Action, StreamMessage
from .snapshot import Snapshot, compose, diff, displayed, snapshot

MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 30
BASELINE_RETRY_SECONDS = 300

Message = tuple[str, str]


@dataclass(frozen=True)
class PendingChange:
    action: Action | None
    fields: frozenset[str] = field(default_factory=frozenset)
    note: str = ""
    attempts: int = 0

    def merge(self, other: PendingChange) -> PendingChange:
        if Action.REMOVED in (self.action, other.action):
            action = Action.REMOVED
        elif Action.CREATED in (self.action, other.action):
            action = Action.CREATED
        else:
            action = other.action or self.action
        fields = self.fields | other.fields if self.fields and other.fields else frozenset()
        return PendingChange(action, fields, other.note or self.note, self.attempts)


class ChangeSyncer:
    def __init__(self, catalog: EventCatalog, cache: SnapshotCache, broadcaster: Broadcaster):
        self._catalog = catalog
        self._cache = cache
        self._broadcaster = broadcaster
        self._pending: dict[str, PendingChange] = {}
        self._align_requested = False
        self._wake = asyncio.Event()
        self._timers: set[asyncio.TimerHandle] = set()
        self._baseline_retry_scheduled = False

    def enqueue(self, message: StreamMessage) -> None:
        change = PendingChange(message.action, frozenset(message.fields), message.note)
        for event_id in message.event_ids:
            self._put(event_id, change)

    def request_alignment(self) -> None:
        self._align_requested = True
        self._wake.set()

    def close(self) -> None:
        for timer in self._timers:
            timer.cancel()
        self._timers.clear()

    async def run_forever(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            pending, self._pending = self._pending, {}
            align, self._align_requested = self._align_requested, False
            try:
                await self._sync(pending, align)
            except Exception as exc:
                log.warning(f"活动对比推送失败: {exc}")

    def _put(self, event_id: str, change: PendingChange) -> None:
        existing = self._pending.get(event_id)
        self._pending[event_id] = existing.merge(change) if existing else change
        self._wake.set()

    def _later(self, delay: float, callback, *args) -> None:
        loop = asyncio.get_running_loop()
        timer: asyncio.TimerHandle

        def fire() -> None:
            self._timers.discard(timer)
            callback(*args)

        timer = loop.call_later(delay, fire)
        self._timers.add(timer)

    def _schedule_baseline_retry(self) -> None:
        if self._baseline_retry_scheduled:
            return
        self._baseline_retry_scheduled = True

        def retry() -> None:
            self._baseline_retry_scheduled = False
            self.request_alignment()

        self._later(BASELINE_RETRY_SECONDS, retry)

    async def _sync(self, pending: dict[str, PendingChange], align: bool) -> None:
        snapshots = self._cache.load()
        trusted = snapshots is not None
        if snapshots is None:
            snapshots = await self._align(None)
            trusted = snapshots is not None
            snapshots = snapshots or {}
            align = False
            if not trusted:
                self._schedule_baseline_retry()

        if pending:
            messages = await self._apply(pending, snapshots)
            if trusted:
                self._cache.save(snapshots)
            await self._broadcaster.broadcast(messages)

        if align:
            await self._align(snapshots)

    async def _apply(self, pending: dict[str, PendingChange], snapshots: dict[str, Snapshot]) -> list[Message]:
        messages: list[Message] = []
        for event_id, change in sorted(pending.items()):
            if message := await self._resolve(event_id, change, snapshots):
                messages.append(message)
        if not messages:
            log.info(f"活动无可推送的变化（WS 下发 {len(pending)} 场）")
        return messages

    async def _resolve(self, event_id: str, change: PendingChange, snapshots: dict[str, Snapshot]) -> Message | None:
        prev = snapshots.get(event_id)
        visible = displayed(change.fields)

        if change.action is Action.UPDATED and change.fields and not visible and not change.note:
            log.info(f"活动 {event_id} 只改动了未展示的字段（{'、'.join(sorted(change.fields))}），不推送")
            return None

        if change.action is Action.REMOVED:
            return await self._removal(event_id, change, snapshots)

        try:
            current = snapshot(await self._catalog.detail(event_id))
        except EventNotFound:
            if change.action is Action.CREATED or prev is None:
                log.info(f"活动 {event_id} 已不存在，跳过")
                return None
            return await self._removal(event_id, change, snapshots)
        except ApiError as exc:
            self._retry(event_id, change, exc)
            return None

        snapshots[event_id] = current
        if change.action is Action.CREATED:
            return Action.CREATED.value, compose(event_id, Action.CREATED, None, current, change.note)

        if prev is None:
            if change.action is Action.UPDATED and (visible or change.note):
                return Action.UPDATED.value, compose(event_id, Action.UPDATED, None, current, change.note, visible)
            log.info(f"活动 {event_id} 没有本地基线，已记录当前状态，不推送")
            return None

        if diff(prev, current) or change.note:
            return Action.UPDATED.value, compose(event_id, Action.UPDATED, prev, current, change.note)
        log.info(f"活动 {event_id} 展示字段无变化，不推送")
        return None

    async def _removal(self, event_id: str, change: PendingChange, snapshots: dict[str, Snapshot]) -> Message | None:
        removed = snapshots.pop(event_id, None)
        if removed is None:
            try:
                removed = snapshot(await self._catalog.detail(event_id))
            except ApiError:
                log.info(f"活动 {event_id} 已移除，但本地没有它的记录，不推送")
                return None
        return Action.REMOVED.value, compose(event_id, Action.REMOVED, removed, None, change.note)

    def _retry(self, event_id: str, change: PendingChange, error: Exception) -> None:
        attempts = change.attempts + 1
        if attempts >= MAX_ATTEMPTS:
            log.warning(f"获取活动详情失败 {event_id}，已重试 {attempts} 次，放弃本次推送: {error}")
            return
        log.warning(f"获取活动详情失败 {event_id}，{RETRY_DELAY_SECONDS} 秒后重试: {error}")
        self._later(RETRY_DELAY_SECONDS, self._put, event_id, replace(change, attempts=attempts))

    async def _align(self, current: dict[str, Snapshot] | None) -> dict[str, Snapshot] | None:
        try:
            fresh = {
                str(item["id"]): snapshot(map_list_item(item))
                async for item in self._catalog.client.iter_all_events()
                if item.get("id")
            }
        except ApiError as exc:
            log.warning(f"拉取活动列表失败，跳过本次对齐: {exc}")
            return None
        if not fresh:
            log.warning("活动列表为空，跳过本次对齐")
            return None

        for event_id, snap in fresh.items():
            snap["groups"] = (current or {}).get(event_id, {}).get("groups", "")
        self._cache.save(fresh)
        if current is None:
            log.info(f"已建立活动基线（{len(fresh)} 场）")
        else:
            changed = sum(1 for k, v in fresh.items() if k not in current or diff(current[k], v))
            changed += sum(1 for k in current if k not in fresh)
            log.info(f"活动缓存已对齐（{len(fresh)} 场，其中 {changed} 场与缓存不同），本次不推送")
        return fresh
