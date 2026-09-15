import os
from datetime import datetime
from importlib.metadata import version

from astrbot.api import logger

BAONLY_URL = "https://beta.baonly.cn/"

# 反调试注入脚本
ANTI_DEBUG_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

const OriginalFunction = window.Function;
window.Function = new Proxy(OriginalFunction, {
    apply(target, thisArg, args) {
        const code = args.join(' ');
        if (code.includes('debugger')) {
            return function() {};
        }
        return Reflect.apply(target, thisArg, args);
    },
    construct(target, args) {
        const code = args.join(' ');
        if (code.includes('debugger')) {
            return function() {};
        }
        return Reflect.construct(target, args);
    }
});

const originalEval = window.eval;
window.eval = new Proxy(originalEval, {
    apply(target, thisArg, args) {
        const code = String(args[0] || '');
        if (code.includes('debugger')) {
            return undefined;
        }
        return Reflect.apply(target, thisArg, args);
    }
});

const origSetInterval = window.setInterval;
window.setInterval = new Proxy(origSetInterval, {
    apply(target, thisArg, args) {
        const fn = String(args[0]);
        if (fn.includes('debugger') || fn.includes('constructor')) {
            return 0;
        }
        return Reflect.apply(target, thisArg, args);
    }
});

const origSetTimeout = window.setTimeout;
window.setTimeout = new Proxy(origSetTimeout, {
    apply(target, thisArg, args) {
        const fn = String(args[0]);
        if (fn.includes('debugger') || fn.includes('constructor')) {
            return 0;
        }
        return Reflect.apply(target, thisArg, args);
    }
});

['log', 'warn', 'error', 'debug', 'info'].forEach(method => {
    const orig = console[method];
    Object.defineProperty(console, method, {
        get: () => orig,
        set: () => {}
    });
});

Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5]
});
Object.defineProperty(navigator, 'languages', {
    get: () => ['zh-CN', 'zh', 'en']
});
"""

SIZE_OPTIONS = {
    4: "4场/页",
    6: "6场/页",
    10: "10场/页",
    20: "20场/页",
    23: "23场/页",
    50: "50场/页",
}


async def close_tour(page):
    """关闭新手教程引导弹窗（点击"不用啦"按钮，正确退出，避免报错）"""
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError

    nudge = page.locator(".tour__nudge")
    try:
        await nudge.wait_for(timeout=2000)
    except PlaywrightTimeoutError:
        return
    if not await nudge.is_visible():
        return
    skip_btn = nudge.locator("button", has_text="不用啦")
    try:
        await skip_btn.first.wait_for(timeout=2000)
        if await skip_btn.first.is_visible():
            await skip_btn.first.click()
            await page.wait_for_timeout(300)
    except PlaywrightTimeoutError:
        pass


async def close_announcement(page):
    """关闭公告弹窗（点击关闭按钮，避免直接删元素导致报错）"""
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError

    # 新版：scrim 遮罩下的公告弹窗
    scrim_btn = page.locator('body > div.scrim.fixed.inset-0 button[aria-label="关闭"]')
    try:
        await scrim_btn.first.wait_for(timeout=2000)
        if await scrim_btn.first.is_visible():
            await scrim_btn.first.click()
            await page.wait_for_timeout(300)
            return
    except PlaywrightTimeoutError:
        pass

    # 旧版：公告中心弹窗
    close_btn = page.locator(".announcement-center-dialog .icon-button")
    try:
        await close_btn.first.wait_for(timeout=2000)
        if await close_btn.first.is_visible():
            await close_btn.first.click()
            await page.wait_for_timeout(300)
    except PlaywrightTimeoutError:
        pass


async def close_overlays(page):
    """截图前关闭公告弹窗与新手教程引导"""
    await close_announcement(page)
    await close_tour(page)


async def reset_mouse(page):
    """将鼠标移到页脚空白区域，清除组件:hover 高亮状态"""
    try:
        size = page.viewport_size
        height = size["height"] if size else 1080
        await page.mouse.move(2, height - 2)
        await page.wait_for_timeout(300)
    except Exception:
        pass


async def wait_for_page_load(page, max_retries=8):
    """等待页面完全加载，包括所有懒加载图片"""
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError

    logger.info("[BAOnly] 等待页面加载...")
    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
    except Exception as e:
        logger.warning(f"[BAOnly] 等待网络空闲超时: {e}")

    for attempt in range(max_retries):
        # 逐步滚动整个页面触发所有懒加载图片
        logger.info(f"[BAOnly] 第 {attempt + 1}/{max_retries} 轮：滚动页面触发懒加载...")
        await page.evaluate("""
            async () => {
                const step = window.innerHeight * 0.75;
                const maxScroll = document.body.scrollHeight;
                for (let y = 0; y < maxScroll; y += step) {
                    window.scrollTo(0, y);
                    await new Promise(r => setTimeout(r, 150));
                }
                window.scrollTo(0, maxScroll);
                await new Promise(r => setTimeout(r, 1500));
            }
        """)

        # 强制所有图片 eager + sync 解码
        await page.evaluate("""
            () => {
                document.querySelectorAll('img').forEach(img => {
                    img.loading = 'eager';
                    img.decoding = 'sync';
                });
            }
        """)
        await page.wait_for_timeout(2000)

        # 使用 decode() 确认图片完全解码
        result = await page.evaluate("""
            async () => {
                const imgs = document.querySelectorAll('img');
                if (imgs.length === 0) return { done: true, total: 0, loaded: 0, failed: 0, pending: 0 };

                let loaded = 0, failed = 0, pending = 0;
                for (const img of [...imgs]) {
                    if (!img.complete) { pending++; continue; }
                    if (img.naturalWidth === 0) { failed++; continue; }
                    try {
                        await img.decode();
                        loaded++;
                    } catch { failed++; }
                }
                return { done: pending === 0, total: imgs.length, loaded, failed, pending };
            }
        """)

        logger.info(
            f"[BAOnly] 图片状态: 共 {result['total']} | 已解码 {result['loaded']} | "
            f"失败 {result['failed']} | 待加载 {result['pending']}"
        )

        if result["done"]:
            if result["failed"] == 0:
                logger.info("[BAOnly] 全部图片加载并解码完成")
            else:
                logger.info(f"[BAOnly] 图片加载完成（{result['failed']} 张加载失败）")
            break

    # 等待浏览器完成合成和绘制
    await page.evaluate("""
        async () => {
            for (let i = 0; i < 5; i++) {
                await new Promise(r => requestAnimationFrame(r));
            }
        }
    """)
    await page.wait_for_timeout(1000)
    # 截图前再次确保教程/公告弹窗被移除（它们可能在首次加载后才出现）
    await close_overlays(page)
    # 移开鼠标，避免组件因悬停(:hover)被高亮
    await reset_mouse(page)
    logger.info("[BAOnly] 页面渲染完成，准备截图")


async def set_page_size(page, size):
    """设置每页显示数量"""
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError

    if size not in SIZE_OPTIONS:
        logger.warning(
            f"[BAOnly] 不支持的每页数量: {size}，可选值: {list(SIZE_OPTIONS.keys())}"
        )
        return

    trigger_btn = page.locator(".pagination-size-control .animated-select-trigger")
    try:
        await trigger_btn.wait_for(timeout=3000)
    except PlaywrightTimeoutError:
        logger.warning("[BAOnly] 未找到每页数量选择按钮")
        return

    current_size_element = trigger_btn.locator("span")
    try:
        current_text = await current_size_element.text_content(timeout=2000)
    except PlaywrightTimeoutError:
        return

    if current_text == SIZE_OPTIONS[size]:
        logger.info(f"[BAOnly] 当前已是 {SIZE_OPTIONS[size]}")
        return

    logger.info("[BAOnly] 点击展开每页数量菜单...")
    await trigger_btn.click()
    await page.wait_for_timeout(500)

    option_text = SIZE_OPTIONS[size]
    logger.info(f"[BAOnly] 尝试选择: {option_text}")
    option_btn = page.locator(f"button:text-is('{option_text}')")

    try:
        await option_btn.wait_for(timeout=3000)
        await option_btn.click()
        await wait_for_page_load(page)
        logger.info(f"[BAOnly] 已切换到 {option_text}")
    except PlaywrightTimeoutError:
        logger.warning(f"[BAOnly] 未找到选项: {option_text}")


def _inject_footer_js(
    playwright_ver: str,
    now_str: str,
    astrbot_ver: str = "",
    plugin_name: str = "",
    plugin_ver: str = "",
) -> str:
    parts = [
        f"截图时间：{now_str}",
        "数据来源自 beta.baonly.cn",
        f"Powered By Playwright v{playwright_ver}",
    ]
    if astrbot_ver:
        parts.append(f"AstrBot v{astrbot_ver}")
    if plugin_name:
        parts.append(f"{plugin_name} v{plugin_ver}")
    parts.append("作者：香草味的纳西妲喵（VanillaNahida）")

    text_content = " | ".join(parts)
    return f"""
        const footer = document.createElement('div');
        footer.style.cssText = 'text-align:center;padding:12px 0;font-size:20px;color:#000000;border-top:1px solid #eee;margin-top:20px;';
        footer.textContent = '{text_content}';
        document.body.appendChild(footer);
    """


async def capture_screenshot(
    page_size: int = 4,
    output_path: str = "screenshot.png",
    user_agent: str = "",
    astrbot_version: str = "",
    plugin_name: str = "",
    plugin_version: str = "",
    proxy_host: str = "",
    proxy_port: str = "",
    proxy_username: str = "",
    proxy_password: str = "",
) -> str:
    """异步截图入口函数（单页，只截当前页）

    Args:
        page_size: 每页显示数量 (4/6/10/20/23/50)
        output_path: 截图保存路径
        user_agent: 自定义 UA
        astrbot_version: AstrBot 版本号
        plugin_name: 插件名称
        plugin_version: 插件版本号
        proxy_host: HTTP 代理地址
        proxy_port: HTTP 代理端口
        proxy_username: HTTP 代理用户名
        proxy_password: HTTP 代理密码

    Returns:
        str: 截图文件路径
    """
    from playwright.async_api import async_playwright

    logger.info(f"[BAOnly] 正在访问 {BAONLY_URL} ...")

    playwright_version = version("playwright")
    now_str = datetime.now().strftime("%Y/%m/%d %H:%M")

    async with async_playwright() as p:
        launch_args = ["--disable-blink-features=AutomationControlled"]
        if proxy_host and proxy_port:
            if proxy_username and proxy_password:
                proxy_server = f"http://{proxy_username}:{proxy_password}@{proxy_host}:{proxy_port}"
            else:
                proxy_server = f"http://{proxy_host}:{proxy_port}"
            launch_args.append(f"--proxy-server={proxy_server}")
            logger.info(f"[BAOnly] 使用代理: http://{proxy_host}:{proxy_port}")
        browser = await p.chromium.launch(
            headless=True,
            args=launch_args,
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=user_agent if user_agent else None,
        )
        page = await context.new_page()
        await page.add_init_script(ANTI_DEBUG_SCRIPT)

        await page.goto(BAONLY_URL, wait_until="networkidle", timeout=60000)

        await close_overlays(page)

        await set_page_size(page, page_size)

        await wait_for_page_load(page)

        await page.evaluate(
            _inject_footer_js(
                playwright_version,
                now_str,
                astrbot_version,
                plugin_name,
                plugin_version,
            )
        )

        await page.screenshot(path=output_path, full_page=True)
        logger.info(f"[BAOnly] 截图已保存至: {output_path}")

        await browser.close()

    return output_path
