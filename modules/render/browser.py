from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from ...utils.log import log
from ..settings import ProxySettings

MAX_CONCURRENT_BROWSERS = 2

_LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]

_SYSTEM_BROWSER_COMMANDS = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "microsoft-edge",
)
_SYSTEM_BROWSER_PATHS = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
)

_slots: asyncio.Semaphore | None = None


def _semaphore() -> asyncio.Semaphore:
    global _slots
    if _slots is None:
        _slots = asyncio.Semaphore(MAX_CONCURRENT_BROWSERS)
    return _slots


def _system_browser() -> str:
    for command in _SYSTEM_BROWSER_COMMANDS:
        if path := shutil.which(command):
            return path
    return next((path for path in _SYSTEM_BROWSER_PATHS if os.path.exists(path)), "")


async def _launch(playwright: Any, proxy: ProxySettings) -> Any:
    options: dict[str, Any] = {"headless": True, "args": _LAUNCH_ARGS}
    if server := proxy.for_playwright():
        options["proxy"] = server
    try:
        return await playwright.chromium.launch(**options)
    except Exception as exc:
        executable = _system_browser()
        if not executable:
            raise
        log.warning(f"Playwright 内置 Chromium 不可用（{exc}），改用系统浏览器: {executable}")
        return await playwright.chromium.launch(executable_path=executable, **options)


@asynccontextmanager
async def open_page(proxy: ProxySettings, **context_options: Any) -> AsyncIterator[Any]:
    from playwright.async_api import async_playwright

    async with _semaphore(), async_playwright() as playwright:
        browser = await _launch(playwright, proxy)
        try:
            context = await browser.new_context(**context_options)
            yield await context.new_page()
        finally:
            await browser.close()
