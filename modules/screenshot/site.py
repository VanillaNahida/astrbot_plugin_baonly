from __future__ import annotations

import asyncio
import json
from functools import cache
from pathlib import Path

from ...utils.files import unique_path
from ...utils.log import log
from ...utils.timefmt import format_clock
from ..meta import ASSETS_DIR, SITE_ORIGIN, TEMP_DIR, RuntimeInfo
from ..render import open_page
from ..settings import Settings

PAGE_SIZES = (4, 6, 8, 10, 20, 23, 50)
DEFAULT_PAGE_SIZE = 8
CAPTURE_MARKER = "data-baonly-capture"
VIEWPORT = {"width": 1920, "height": 1080}
LIST_SELECTOR = ".spotlight-grid"
GOTO_TIMEOUT_MS = 60_000
IDLE_TIMEOUT_MS = 15_000
IMAGE_TIMEOUT_MS = 20_000


@cache
def _script(name: str) -> str:
    return (ASSETS_DIR / "scripts" / f"{name}.js").read_text(encoding="utf-8").strip()


class SiteScreenshotter:
    def __init__(self, settings: Settings, runtime: RuntimeInfo):
        self._settings = settings
        self._runtime = runtime

    async def capture(self, page_size: int) -> Path:
        if self._settings.extra_wait_seconds:
            await asyncio.sleep(self._settings.extra_wait_seconds)

        output = unique_path(TEMP_DIR, f"baonly_page{page_size}_", ".png")
        async with open_page(
            self._settings.proxy,
            viewport=VIEWPORT,
            user_agent=self._settings.user_agent,
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            reduced_motion="reduce",
        ) as page:
            await page.add_init_script(script=f"({_script('bootstrap')})({json.dumps(page_size)})")
            log.info(f"正在访问 {SITE_ORIGIN} ...")
            await page.goto(SITE_ORIGIN + "/", wait_until="load", timeout=GOTO_TIMEOUT_MS)
            await self._wait_quietly(page)

            stats = await page.evaluate(_script("settle"), IMAGE_TIMEOUT_MS)
            log.info(f"图片状态: 共 {stats['total']} | 未完成 {stats['pending']} | 加载失败 {stats['broken']}")

            framed = await page.evaluate(_script("frame"), CAPTURE_MARKER)
            target = f"[{CAPTURE_MARKER}]"
            await page.evaluate(_script("footer"), [self._runtime.footer(format_clock()), target])
            if framed:
                await page.locator(target).screenshot(
                    path=str(output), animations="disabled", timeout=GOTO_TIMEOUT_MS
                )
            else:
                log.warning("未找到活动列表区域，改为整页截图")
                await page.screenshot(
                    path=str(output), full_page=True, animations="disabled", timeout=GOTO_TIMEOUT_MS
                )

        log.info(f"截图已保存至: {output}")
        return output

    @staticmethod
    async def _wait_quietly(page) -> None:
        from playwright.async_api import TimeoutError as PlaywrightTimeout

        try:
            await page.wait_for_load_state("networkidle", timeout=IDLE_TIMEOUT_MS)
        except PlaywrightTimeout:
            log.warning("等待网络空闲超时，继续截图")
        try:
            await page.wait_for_selector(LIST_SELECTOR, state="attached", timeout=IDLE_TIMEOUT_MS)
        except PlaywrightTimeout:
            log.warning("未等到活动列表渲染，继续截图")
