from __future__ import annotations

import asyncio
import random
from typing import Any

from ...utils.log import log
from ..subscriptions import Subscription, SubscriptionStore
from ..subscriptions.umo import is_group_umo
from .status import StreamStatus

JITTER_SECONDS = (0.5, 1.0)


class Broadcaster:
    def __init__(
        self,
        context: Any,
        store: SubscriptionStore,
        status: StreamStatus,
        *,
        base_delay: float,
        groups_disabled: bool,
    ):
        self._context = context
        self._store = store
        self._status = status
        self._base_delay = base_delay
        self._groups_disabled = groups_disabled

    async def broadcast(self, messages: list[tuple[str, str]]) -> None:
        if not messages:
            return
        targets = self._targets(await self._store.list())
        if not targets:
            log.info("无可用推送渠道，仅更新活动缓存")
            return

        from astrbot.api.event import MessageChain

        for label, text in messages:
            log.info(f"推送变更[{label}]，共 {len(targets)} 个订阅渠道")
            chain = MessageChain().message(text)
            for sub in targets:
                await asyncio.sleep(self._base_delay + random.uniform(*JITTER_SECONDS))
                await self._send(sub, chain)

    async def _send(self, sub: Subscription, chain: Any) -> None:
        try:
            delivered = await self._context.send_message(sub.umo, chain)
        except Exception as exc:
            log.warning(f"推送失败 {sub.umo}: {exc}")
            return
        if delivered:
            self._status.on_pushed()
            log.info(f"已推送到: {sub.label}")
        else:
            log.warning(f"推送目标不可达: {sub.label}（{sub.umo}）")

    def _targets(self, subs: list[Subscription]) -> list[Subscription]:
        if not self._groups_disabled:
            return subs
        private = [s for s in subs if not s.is_group and not is_group_umo(s.umo)]
        log.info(
            f"已开启「关闭群发」（仅供测试使用），跳过 {len(subs) - len(private)} 个群聊渠道，"
            f"仅推送 {len(private)} 个私聊渠道"
        )
        return private
