from __future__ import annotations

import asyncio
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

from ...utils.files import purge_older_than, unique_path
from ...utils.log import log
from ..meta import TEMP_DIR
from ..settings import Settings
from .browser import open_page
from .templates import CARD_WIDTH

RETRY_DELAY_SECONDS = 1.0
TEMP_TTL_SECONDS = 6 * 3600

_WAIT_FONTS = """
async () => {
  const links = [...document.querySelectorAll('link[rel=stylesheet]')];
  await Promise.all(links.map(link => link.sheet ? null : new Promise(done => {
    link.addEventListener('load', done, {once: true});
    link.addEventListener('error', done, {once: true});
  })));
  await Promise.all(['400 13px Blueaka', '700 13px Blueaka', '700 22px Blueaka'].map(f => document.fonts.load(f)));
  await document.fonts.ready;
}
"""

_WAIT_IMAGES = """
async () => {
  await Promise.all([...document.images].map(img => img.decode().catch(() => {})));
}
"""

_IMAGE_SIGNATURES = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")

Backend = Callable[[str, str], Awaitable[Path]]


class RenderError(RuntimeError):
    pass


class CardRenderer:
    def __init__(self, settings: Settings):
        self._settings = settings

    async def render(self, html: str, prefix: str) -> Path:
        purge_older_than(TEMP_DIR, TEMP_TTL_SECONDS)
        backends: dict[str, Backend] = {
            "astrbot": self._via_astrbot,
            "playwright": self._via_playwright,
        }
        order = ["astrbot", "playwright"] if self._settings.render_mode == "auto" else [self._settings.render_mode]

        last_error: Exception | None = None
        for name in order:
            try:
                return await self._with_retry(name, backends[name], html, prefix)
            except Exception as exc:
                log.warning(f"{name} 渲染已重试 {self._settings.render_retry} 次仍失败: {exc}")
                last_error = exc
        raise RenderError(f"卡片渲染失败: {last_error}") from last_error

    async def _with_retry(self, name: str, backend: Backend, html: str, prefix: str) -> Path:
        attempts = self._settings.render_retry
        for attempt in range(1, attempts):
            try:
                return await backend(html, prefix)
            except Exception as exc:
                log.warning(f"{name} 渲染失败（第 {attempt}/{attempts} 次）: {exc}")
                await asyncio.sleep(RETRY_DELAY_SECONDS)
        return await backend(html, prefix)

    async def _via_astrbot(self, html: str, prefix: str) -> Path:
        from astrbot.api import html_renderer

        result = await html_renderer.render_custom_template(
            "{{ html | safe }}",
            {"html": html},
            return_url=False,
            options={
                "full_page": True,
                "type": "jpeg",
                "quality": 90,
                "viewport_width": CARD_WIDTH,
                "device_scale_factor_level": "ultra",
            },
        )
        source = Path(_local_path(result))
        if not _is_image(source):
            raise RenderError("文转图服务返回的不是图片，可能暂时不可用")
        output = unique_path(TEMP_DIR, prefix, ".jpg")
        shutil.copyfile(source, output)
        return output

    async def _via_playwright(self, html: str, prefix: str) -> Path:
        output = unique_path(TEMP_DIR, prefix, ".png")
        async with open_page(
            self._settings.proxy,
            viewport={"width": CARD_WIDTH, "height": 900},
            device_scale_factor=2,
            user_agent=self._settings.user_agent,
        ) as page:
            await page.set_content(html, wait_until="domcontentloaded", timeout=15_000)
            await _settle(page, _WAIT_FONTS, timeout=10)
            await _settle(page, _WAIT_IMAGES, timeout=15)
            await page.wait_for_timeout(300)
            await page.screenshot(path=str(output), full_page=True, timeout=15_000)
        return output


async def _settle(page, script: str, timeout: float) -> None:
    try:
        await asyncio.wait_for(page.evaluate(script), timeout=timeout)
    except Exception as exc:
        log.debug(f"等待页面资源超时，继续截图: {exc}")


def _is_image(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            head = fh.read(12)
    except OSError:
        return False
    return head.startswith(_IMAGE_SIGNATURES) or (head[:4] == b"RIFF" and head[8:12] == b"WEBP")


def _local_path(value: str) -> str:
    if value.startswith("file://"):
        return url2pathname(urlparse(value).path)
    return value
