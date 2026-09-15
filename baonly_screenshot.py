import os
from datetime import datetime
from importlib.metadata import version

from astrbot.api import logger

BAONLY_URL = "https://www.baonly.cn/"

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


async def wait_for_page_load(page):
    """等待页面加载，触发懒加载图片后等待图片完成"""
    logger.info("[BAOnly] 等待页面加载...")
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass

    # 滚动页面一次，触发所有懒加载图片
    logger.info("[BAOnly] 滚动触发懒加载图片...")
    await page.evaluate("""
        async () => {
            const step = window.innerHeight * 0.8;
            const maxScroll = document.body.scrollHeight;
            for (let y = 0; y < maxScroll; y += step) {
                window.scrollTo(0, y);
                await new Promise(r => setTimeout(r, 120));
            }
            window.scrollTo(0, maxScroll);
            await new Promise(r => setTimeout(r, 400));
            window.scrollTo(0, 0);
            await new Promise(r => setTimeout(r, 200));
        }
    """)

    # 等待所有图片加载完成
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    try:
        await page.wait_for_function("""
            () => {
                const imgs = document.querySelectorAll('img');
                if (imgs.length === 0) return true;
                return [...imgs].every(img => img.complete);
            }
        """, timeout=15000)
    except PlaywrightTimeoutError:
        pass
    await page.wait_for_timeout(500)

    # 等待渲染帧完成
    await page.evaluate("""
        async () => {
            for (let i = 0; i < 3; i++) {
                await new Promise(r => requestAnimationFrame(r));
            }
        }
    """)
    logger.info("[BAOnly] 页面加载完成，准备截图")


async def set_page_size(page, size):
    """设置每页显示数量"""
    if size not in SIZE_OPTIONS:
        logger.warning(f"[BAOnly] 不支持的每页数量: {size}，可选值: {list(SIZE_OPTIONS.keys())}")
        return

    from playwright.async_api import TimeoutError as PlaywrightTimeoutError

    trigger_btn = page.locator(".pagination-size-control .animated-select-trigger")
    try:
        await trigger_btn.wait_for(timeout=3000)
    except PlaywrightTimeoutError:
        logger.warning("[BAOnly] 未找到每页数量选择按钮")
        return

    current_size_element = trigger_btn.locator("span")
    try:
        current_text = await current_size_element.text_content(timeout=3000)
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


async def go_to_page(page, page_num):
    """跳转到指定页码"""
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError

    page_btn = page.locator(f".pagination-page:text-is('{page_num}')")
    try:
        await page_btn.wait_for(timeout=3000)
        logger.info(f"[BAOnly] 点击第 {page_num} 页...")
        await page_btn.click()
        await wait_for_page_load(page)
        logger.info(f"[BAOnly] 已跳转到第 {page_num} 页")
        return True
    except PlaywrightTimeoutError:
        logger.warning(f"[BAOnly] 未找到第 {page_num} 页按钮")
        return False


def _inject_footer_js(
    playwright_ver: str,
    now_str: str,
    astrbot_ver: str = "",
    plugin_name: str = "",
    plugin_ver: str = "",
) -> str:
    parts = [
        f"截图时间：{now_str}",
        "数据来源自 www.baonly.cn",
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
    page_num: int = 1,
    user_agent: str = "",
    astrbot_version: str = "",
    plugin_name: str = "",
    plugin_version: str = "",
    proxy_host: str = "",
    proxy_port: str = "",
    proxy_username: str = "",
    proxy_password: str = "",
) -> str:
    """异步截图入口函数

    Args:
        page_size: 每页显示数量 (4/6/10/20/23/50)
        output_path: 截图保存路径
        page_num: 页码
        user_agent: 自定义 UA
        astrbot_version: AstrBot 版本号
        plugin_name: 插件名称
        plugin_version: 插件版本号
        proxy_host: SOCKS5 代理地址
        proxy_port: SOCKS5 代理端口
        proxy_username: SOCKS5 代理用户名
        proxy_password: SOCKS5 代理密码

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

        try:
            close_btn = page.locator(".announcement-center-dialog .icon-button")
            await close_btn.wait_for(timeout=5000)
            await close_btn.click()
            await page.wait_for_timeout(500)
        except Exception:
            pass

        if page_size != 4:
            await set_page_size(page, page_size)

        await wait_for_page_load(page)

        if page_num > 1:
            await go_to_page(page, page_num)

        # 隐藏右下角公告浮岛
        try:
            island = page.locator(".announcement-island")
            await island.evaluate("el => el.style.display = 'none'")
        except Exception:
            pass

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
