from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from ...utils.log import log
from ..meta import STREAM_URL
from ..settings import Settings
from .protocol import CLOSING, StreamMessage, parse
from .status import KEY_INVALID, StreamStatus

INVALID_KEY_RETRY_SECONDS = 600
OPEN_TIMEOUT_SECONDS = 15

MessageHandler = Callable[[StreamMessage], Awaitable[None]]


class StreamConnection:
    def __init__(self, settings: Settings, status: StreamStatus, on_message: MessageHandler):
        self._settings = settings
        self._status = status
        self._on_message = on_message

    async def run_forever(self) -> None:
        self._status.running = True
        try:
            while True:
                await self._session()
                delay = self._reconnect_delay()
                log.info(f"{delay:.0f} 秒后重连 WebSocket...")
                await asyncio.sleep(delay)
        finally:
            self._status.running = False

    def _reconnect_delay(self) -> float:
        interval = self._settings.ws_reconnect_interval
        if self._status.last_close_code == KEY_INVALID:
            return max(interval, INVALID_KEY_RETRY_SECONDS)
        return interval

    async def _session(self) -> None:
        from websockets.asyncio.client import connect
        from websockets.exceptions import ConnectionClosed, InvalidStatus

        log.info(f"连接 WebSocket: {STREAM_URL}")
        try:
            async with connect(
                STREAM_URL,
                additional_headers={"x-api-key": self._settings.token},
                user_agent_header=self._settings.user_agent,
                ping_interval=self._settings.ws_ping_interval,
                ping_timeout=self._settings.ws_ping_interval,
                open_timeout=OPEN_TIMEOUT_SECONDS,
            ) as ws:
                log.info("WebSocket 已连接")
                self._status.on_connected()
                try:
                    async for raw in ws:
                        await self._dispatch(raw)
                except ConnectionClosed:
                    pass
                finally:
                    self._status.on_disconnected(ws.close_code, (ws.close_reason or "").strip())
        except InvalidStatus as exc:
            self._status.on_handshake_rejected(getattr(exc.response, "status_code", None))
        except Exception as exc:
            self._status.on_error(f"{type(exc).__name__}: {exc}")

    async def _dispatch(self, raw: str | bytes) -> None:
        message = parse(raw) if raw else None
        if message is None:
            log.warning(f"推送消息解析失败: {str(raw)[:200]}")
            return
        if message.type == CLOSING:
            self._status.on_closing(message.code, message.reason)
            return
        try:
            await self._on_message(message)
        except Exception as exc:
            log.warning(f"处理推送消息失败: {exc}")
