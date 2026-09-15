import os
import time
from importlib.metadata import version

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger, AstrBotConfig

from .tools.baonly_query import BAOnlyQueryTool
from .baonly_screenshot import capture_screenshot

VALID_PAGE_SIZES = [4, 6, 10, 20, 23, 50]
PLUGIN_NAME = "astrbot_plugin_baonly"
PLUGIN_VERSION = "1.0.0"


def _get_version_safe(package: str) -> str:
    try:
        return version(package)
    except Exception:
        return ""


class BAOnlyPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.config = config if config is not None else {}

        self._astrbot_version = _get_version_safe("astrbot")
        self._plugin_version = PLUGIN_VERSION

        self._tool = BAOnlyQueryTool()
        self._tool.set_config(self.config)
        self.context.add_llm_tools(self._tool)
        logger.info("[BAOnly] 插件已初始化，LLM 工具已注册")

    @filter.command("bao", alias="BAO")
    async def baonly_default(self, event: AstrMessageEvent):
        """截图 BAOnly 网页活动列表，默认每页 4 场"""
        yield event.plain_result("正在截图，页数：4，请稍后……")
        async for result in self._do_screenshot(event, 4):
            yield result

    @filter.command_group("baonly")
    async def baonly(self):
        pass

    @baonly.command("page")
    async def baonly_page(self, event: AstrMessageEvent, page_size: int = 4):
        """截图 BAOnly 网页活动列表，可指定每页显示数量(4/6/10/20/23/50) 如：baonly page 4"""
        if page_size not in VALID_PAGE_SIZES:
            sizes_str = ", ".join(map(str, VALID_PAGE_SIZES))
            yield event.plain_result(
                f"不支持的每页数量: {page_size}，可选值: {sizes_str}"
            )
            return

        yield event.plain_result(f"正在截图，页数：{page_size}，请稍后……")
        async for result in self._do_screenshot(event, page_size):
            yield result

    async def _do_screenshot(self, event: AstrMessageEvent, page_size: int):
        user_agent = self.config.get(
            "user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
        )

        output_dir = os.path.abspath(os.path.join("data", "temp", PLUGIN_NAME))
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(
            output_dir, f"baonly_page{page_size}_{int(time.time())}.png"
        )

        extra_wait = self.config.get("extra_wait_seconds", 0)
        if extra_wait > 0:
            import asyncio
            logger.info(f"[BAOnly] 额外等待 {extra_wait} 秒...")
            await asyncio.sleep(extra_wait)

        try:
            await capture_screenshot(
                page_size=page_size,
                output_path=output_path,
                page_num=1,
                user_agent=user_agent,
                astrbot_version=self._astrbot_version,
                plugin_name=PLUGIN_NAME,
                plugin_version=self._plugin_version,
                proxy_host=self.config.get("proxy_host", ""),
                proxy_port=self.config.get("proxy_port", ""),
                proxy_username=self.config.get("proxy_username", ""),
                proxy_password=self.config.get("proxy_password", ""),
            )
            yield event.image_result(output_path)
        except Exception as e:
            logger.error(f"[BAOnly] 截图失败: {e}", exc_info=True)
            yield event.plain_result(f"截图失败: {str(e)}")

    async def terminate(self):
        """插件卸载/停用时调用"""
        logger.info("[BAOnly] 插件已卸载")
