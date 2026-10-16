from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..utils.text import clean, to_bool, to_float, to_int

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)

RENDER_MODES = ("auto", "astrbot", "playwright")


@dataclass(frozen=True)
class ProxySettings:
    host: str = ""
    port: str = ""
    username: str = ""
    password: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.host and self.port)

    def for_playwright(self) -> dict[str, str] | None:
        if not self.enabled:
            return None
        proxy = {"server": f"http://{self.host}:{self.port}"}
        if self.username:
            proxy["username"] = self.username
            proxy["password"] = self.password
        return proxy


@dataclass(frozen=True)
class Settings:
    token: str
    user_agent: str
    proxy: ProxySettings
    extra_wait_seconds: float
    detail_image_enabled: bool
    render_mode: str
    render_retry: int
    disable_group_push: bool
    push_delay_seconds: float
    ws_ping_interval: int
    ws_reconnect_interval: int
    events_page_size: int

    @classmethod
    def from_config(cls, config: Mapping[str, Any] | None) -> Settings:
        cfg = config or {}
        mode = clean(cfg.get("detail_render_mode")).lower()
        return cls(
            token=clean(cfg.get("token")),
            user_agent=clean(cfg.get("user_agent")) or DEFAULT_USER_AGENT,
            proxy=ProxySettings(
                host=clean(cfg.get("proxy_host")),
                port=clean(cfg.get("proxy_port")),
                username=clean(cfg.get("proxy_username")),
                password=clean(cfg.get("proxy_password")),
            ),
            extra_wait_seconds=to_float(cfg.get("extra_wait_seconds"), 0, lo=0, hi=600),
            detail_image_enabled=to_bool(cfg.get("detail_image_enabled"), True),
            render_mode=mode if mode in RENDER_MODES else "auto",
            render_retry=to_int(cfg.get("detail_render_retry"), 3, lo=1, hi=10),
            disable_group_push=to_bool(cfg.get("disable_group_push"), False),
            push_delay_seconds=to_float(cfg.get("push_delay_seconds"), 0, lo=0, hi=600),
            ws_ping_interval=to_int(cfg.get("ws_ping_interval"), 30, lo=5, hi=3600),
            ws_reconnect_interval=to_int(cfg.get("ws_reconnect_interval"), 30, lo=1, hi=86400),
            events_page_size=to_int(cfg.get("events_page_size"), 20, lo=1, hi=500),
        )
