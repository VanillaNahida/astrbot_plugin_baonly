from __future__ import annotations

import time
from dataclasses import dataclass

from ...utils.log import log
from ...utils.timefmt import format_duration, now

KEY_INVALID = 4401
NO_PERMISSION = 4403
TOO_MANY = 4429
MAINTENANCE = 4503
NORMAL_CLOSES = (None, 1000, 1001, 1006)

_CLOSE_REASONS = {
    KEY_INVALID: "API Key 无效或已停用",
    NO_PERMISSION: "API Key 没有推送权限",
    TOO_MANY: "同一 Key 的连接数超限",
    MAINTENANCE: "站点进入维护模式",
}


def _stamp() -> str:
    return now().strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class StreamStatus:
    token_configured: bool
    running: bool = False
    connected_since: float | None = None
    key_valid: bool | None = None
    maintenance: bool = False
    scopes: tuple[str, ...] = ()
    last_disconnect: tuple[str, str] | None = None
    announced_close: tuple[int | None, str] | None = None
    push_count: int = 0
    last_push_at: str = ""
    last_close_code: int | None = None

    @property
    def connected(self) -> bool:
        return self.connected_since is not None

    def on_connected(self) -> None:
        self.connected_since = time.time()
        self.last_close_code = None
        self.maintenance = False
        self.announced_close = None

    def on_ready(self, scopes: tuple[str, ...]) -> None:
        self.scopes = scopes
        self.key_valid = True

    def on_closing(self, code: int | None, reason: str) -> None:
        self.announced_close = (code, reason or "服务端主动断开")
        self._apply_code(code)
        log.warning(f"服务端即将断开（code={code}）：{reason or _CLOSE_REASONS.get(code or 0, '')}")

    def on_disconnected(self, code: int | None, reason: str) -> None:
        self.connected_since = None
        if self.announced_close is not None:
            announced_code, announced_reason = self.announced_close
            if code in NORMAL_CLOSES:
                code = announced_code
            reason = announced_reason or reason
            self.announced_close = None

        self.last_close_code = code
        self._apply_code(code)
        reason = reason or _CLOSE_REASONS.get(code or 0, "") or "连接已关闭"
        self.last_disconnect = (_stamp(), reason)
        if code == KEY_INVALID:
            log.error(f"WebSocket 断开：{reason}")
        elif code not in NORMAL_CLOSES:
            log.warning(f"WebSocket 断开：{reason}（关闭码 {code}）")
        else:
            log.info(f"WebSocket 断开：{reason}")

    def on_handshake_rejected(self, http_status: int | None) -> None:
        self.connected_since = None
        if http_status == 401:
            self.key_valid = False
            reason = "API Key 无效或已停用（HTTP 401）"
        elif http_status == 403:
            reason = "API Key 没有推送权限（HTTP 403）"
        else:
            reason = f"WebSocket 握手失败（HTTP {http_status or '未知'}）"
        self.last_close_code = KEY_INVALID if http_status == 401 else None
        self.last_disconnect = (_stamp(), reason)
        log.error(reason)

    def on_error(self, reason: str) -> None:
        self.connected_since = None
        self.last_disconnect = (_stamp(), reason)
        log.warning(f"WebSocket 连接中断: {reason}")

    def on_pushed(self) -> None:
        self.push_count += 1
        self.last_push_at = _stamp()

    def _apply_code(self, code: int | None) -> None:
        if code == KEY_INVALID:
            self.key_valid = False
        elif code in (NO_PERMISSION, TOO_MANY, MAINTENANCE):
            self.key_valid = True
        if code == MAINTENANCE:
            self.maintenance = True

    def describe(self) -> list[str]:
        if not self.token_configured:
            return ["WebSocket 推送：未配置 API Key（token）", "提示：请在插件配置中填写 token 后重启插件。"]

        if self.connected_since is not None:
            lines = [f"WebSocket 推送：已连接（已连接 {format_duration(time.time() - self.connected_since)}）"]
        elif self.running:
            lines = ["WebSocket 推送：未连接，自动重连中……"]
        else:
            lines = ["WebSocket 推送：未连接"]

        lines.append(
            {True: "API Key：有效", False: "API Key：无效或已停用（请检查插件配置中的 token）"}.get(
                self.key_valid, "API Key：未知（等待首次连接确认）"
            )
        )
        if self.maintenance:
            lines.append("站点状态：维护模式中（维护结束后会自动恢复连接）")
        lines.append("推送权限：" + ("、".join(self.scopes) if self.scopes else "未知"))
        if self.last_disconnect:
            lines.append(f"最近断开：{self.last_disconnect[0]}（{self.last_disconnect[1]}）")
        if self.push_count:
            extra = f"，最近于 {self.last_push_at}" if self.last_push_at else ""
            lines.append(f"累计推送：{self.push_count} 次{extra}")
        else:
            lines.append("累计推送：0 次")
        return lines
