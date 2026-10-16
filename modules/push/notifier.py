from __future__ import annotations

import asyncio
from typing import Any

from ...utils.log import log
from ..events import EventCatalog
from ..settings import Settings
from ..subscriptions import SubscriptionStore
from .broadcaster import Broadcaster
from .cache import SnapshotCache
from .connection import StreamConnection
from .protocol import MAINTENANCE, READY, StreamMessage
from .status import StreamStatus
from .syncer import ChangeSyncer


class StreamNotifier:
    def __init__(self, context: Any, settings: Settings, catalog: EventCatalog, store: SubscriptionStore):
        self.status = StreamStatus(token_configured=bool(settings.token))
        broadcaster = Broadcaster(
            context,
            store,
            self.status,
            base_delay=settings.push_delay_seconds,
            groups_disabled=settings.disable_group_push,
        )
        self._syncer = ChangeSyncer(catalog, SnapshotCache(), broadcaster)
        self._connection = StreamConnection(settings, self.status, self._handle)
        self._tasks: list[asyncio.Task] = []
        self._last_seq: int | None = None

    def start(self) -> None:
        if not self.status.token_configured:
            log.warning("未配置 token，跳过 WebSocket 订阅")
            return
        if self._tasks:
            return
        self._tasks = [
            asyncio.create_task(self._connection.run_forever(), name="baonly-stream"),
            asyncio.create_task(self._syncer.run_forever(), name="baonly-sync"),
        ]
        log.info("WebSocket 推送任务已启动")

    async def stop(self) -> None:
        self._syncer.close()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    def describe_status(self) -> list[str]:
        return self.status.describe()

    async def _handle(self, message: StreamMessage) -> None:
        if message.type == READY:
            self.status.on_ready(message.scopes)
            self._last_seq = None
            log.info(f"流已就绪，权限: {list(message.scopes)}")
            self._syncer.request_alignment()
            return

        self._track_sequence(message)

        if message.type == MAINTENANCE:
            self.status.maintenance = bool(message.enabled)
            log.info(f"站点维护模式{'开启' if message.enabled else '关闭'}")
            return

        if message.is_event_change:
            note = f"，备注：{message.note}" if message.note else ""
            log.info(f"收到活动变更推送（{message.type}，{len(message.event_ids)} 场{note}）: {message.preview}")
            self._syncer.enqueue(message)
            return

        if message.type.startswith("event"):
            log.info(f"推送未含活动 ID，仅对齐缓存: {message.preview}")
            self._syncer.request_alignment()
            return

        log.info(f"收到推送: {message.preview}")

    def _track_sequence(self, message: StreamMessage) -> None:
        if message.seq is None:
            return
        if self._last_seq is not None and message.seq > self._last_seq + 1:
            log.warning(f"推送序号从 {self._last_seq} 跳到 {message.seq}，中间的变更已丢失，稍后静默对齐缓存")
            self._syncer.request_alignment()
        self._last_seq = message.seq
