import os
import sys
import argparse
import subprocess
from datetime import datetime
from importlib.metadata import version
from playwright.sync_api import sync_playwright

url = "https://beta.baonly.cn/"

# 反调试注入脚本
anti_debug_script = """
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

def close_tour(page):
    """关闭新手教程引导弹窗（点击“不用啦”按钮，正确退出，避免报错）"""
    nudge = page.locator(".tour__nudge")
    if not nudge.is_visible(timeout=2000):
        return
    skip_btn = nudge.locator("button", has_text="不用啦")
    if skip_btn.first.is_visible(timeout=2000):
        skip_btn.first.click()
        page.wait_for_timeout(300)

def close_announcement(page):
    """关闭公告弹窗（点击关闭按钮，避免直接删元素导致报错）"""
    # 新版：scrim 遮罩下的公告弹窗
    scrim_btn = page.locator('body > div.scrim.fixed.inset-0 button[aria-label="关闭"]')
    if scrim_btn.first.is_visible(timeout=2000):
        scrim_btn.first.click()
        page.wait_for_timeout(300)
        return
    # 旧版：公告中心弹窗
    close_btn = page.locator(".announcement-center-dialog .icon-button")
    if close_btn.first.is_visible(timeout=2000):
        close_btn.first.click()
        page.wait_for_timeout(300)

def close_overlays(page):
    """截图前关闭公告弹窗与新手教程引导"""
    close_announcement(page)
    close_tour(page)

def reset_mouse(page):
    """将鼠标移到页脚空白区域，清除组件:hover 高亮状态"""
    try:
        height = page.viewport_size["height"]
        page.mouse.move(2, height - 2)
        page.wait_for_timeout(300)
    except Exception:
        pass

def wait_for_page_load(page, max_retries=8):
    """等待页面完全加载，包括所有懒加载图片"""
    print("等待页面加载完成...")
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception as e:
        print(f"等待网络空闲超时: {e}")

    for attempt in range(max_retries):
        # 逐步滚动整个页面触发所有懒加载图片
        print(f"轮次 {attempt + 1}/{max_retries}: 滚动页面触发懒加载...")
        page.evaluate("""
            async () => {
                const step = window.innerHeight * 0.75;
                const maxScroll = document.body.scrollHeight;
                for (let y = 0; y < maxScroll; y += step) {
                    window.scrollTo(0, y);
                    await new Promise(r => setTimeout(r, 150));
                }
                // 滚动到页面底部（页脚）后停留，等待下方懒加载组件显现并完成淡入
                window.scrollTo(0, maxScroll);
                await new Promise(r => setTimeout(r, 1500));
                // 不滚回顶部，保持页面停在底部，避免下方组件再次被隐藏
            }
        """)

        # 强制所有图片 eager + sync 解码
        page.evaluate("""
            () => {
                document.querySelectorAll('img').forEach(img => {
                    img.loading = 'eager';
                    img.decoding = 'sync';
                });
            }
        """)
        page.wait_for_timeout(2000)

        # 使用 decode() 确认图片完全解码
        result = page.evaluate("""
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

        print(f"  图片状态: 共 {result['total']} | 已解码 {result['loaded']} | "
              f"失败 {result['failed']} | 待加载 {result['pending']}")

        if result["done"]:
            if result["failed"] == 0:
                print(f"  全部图片加载并解码完成")
            else:
                print(f"  图片加载完成（{result['failed']} 张加载失败）")
            break
    else:
        print(f"  达到最大重试次数，继续截图")

    # 等待浏览器完成合成和绘制
    page.evaluate("""
        async () => {
            for (let i = 0; i < 5; i++) {
                await new Promise(r => requestAnimationFrame(r));
            }
        }
    """)
    page.wait_for_timeout(1000)
    # 截图前再次确保教程/公告弹窗被移除（它们可能在首次加载后才出现）
    close_overlays(page)
    # 移开鼠标，避免组件因悬停(:hover)被高亮
    reset_mouse(page)
    print("页面渲染完成，准备截图")

def set_page_size(page, size):
    """设置每页显示数量"""
    size_options = {
        4: "4场/页",
        6: "6场/页",
        10: "10场/页",
        20: "20场/页",
        23: "23场/页",
        50: "50场/页"
    }

    if size not in size_options:
        print(f"不支持的每页数量: {size}，可选值: {list(size_options.keys())}")
        return

    trigger_btn = page.locator(".pagination-size-control .animated-select-trigger")
    if not trigger_btn.is_visible(timeout=3000):
        print("未找到每页数量选择按钮")
        return

    current_size = trigger_btn.locator("span")
    current_text = current_size.text_content(timeout=2000)
    if current_text == size_options[size]:
        print(f"当前已是 {size_options[size]}")
        return

    print(f"点击展开每页数量菜单...")
    trigger_btn.click()
    page.wait_for_timeout(500)

    option_text = size_options[size]
    print(f"尝试选择: {option_text}")
    option_btn = page.locator(f"button:text-is('{option_text}')")

    if option_btn.is_visible(timeout=3000):
        option_btn.click()
        wait_for_page_load(page)
        print(f"已切换到 {option_text}")
    else:
        print(f"未找到选项: {option_text}")

def go_to_page(page, page_num):
    """跳转到指定页码"""
    page_btn = page.locator(f".pagination-page:text-is('{page_num}')")
    if page_btn.is_visible(timeout=3000):
        print(f"点击第 {page_num} 页...")
        page_btn.click()
        wait_for_page_load(page)
        print(f"已跳转到第 {page_num} 页")
        return True
    else:
        print(f"未找到第 {page_num} 页按钮")
        return False

def inject_footer(page):
    """注入页脚版本信息（追加到列表元素内部，确保被元素截图包含）"""
    playwright_version = version("playwright")
    now_str = datetime.now().strftime("%Y/%m/%d %H:%M")
    page.evaluate(f"""
        const footer = document.createElement('div');
        footer.style.cssText = 'text-align:center;padding:12px 0;font-size:20px;color:#999;border-top:1px solid #eee;margin-top:20px;';
        footer.textContent = '截图时间：{now_str} | 数据来源自 www.baonly.cn | Powered By Playwright v{playwright_version} | 作者：香草味的纳西妲喵（VanillaNahida）';
        document.body.appendChild(footer);
    """)

def capture_screenshot(page, output_path):
    """截取完整页面"""
    page.screenshot(path=output_path, full_page=True)
    print(f"截图已保存至: {output_path}")

def get_total_pages(page):
    """获取总页数"""
    try:
        last_page_btn = page.locator(".pagination-page.edge-right")
        if last_page_btn.is_visible(timeout=2000):
            return int(last_page_btn.text_content())
        return 1
    except:
        return 1

def get_chrome_path():
    """获取系统 Chrome 路径"""
    if sys.platform == "win32":
        # Windows 常见路径
        paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe")
        ]
        for path in paths:
            if os.path.exists(path):
                return path
    elif sys.platform == "darwin":  # macOS
        return "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    else:  # Linux
        return "/usr/bin/google-chrome"

def main():
    parser = argparse.ArgumentParser(description='BAOnly网页截图工具')
    parser.add_argument('--page', type=int, default=1, help='指定页码（默认第1页）')
    parser.add_argument('--page-size', type=int, default=4, choices=[4, 6, 10, 20, 23, 50],
                        help='每页显示数量（默认4场/页）')
    parser.add_argument('--all', action='store_true', help='遍历所有页面截图')
    parser.add_argument('--output', default=None, help='输出文件名')
    args = parser.parse_args()

    print(f"正在访问 {url} ...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=get_chrome_path(),  # 使用系统浏览器
            headless=False,
            args=["--disable-blink-features=AutomationControlled"]
        )
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.add_init_script(anti_debug_script)
        page.goto(url, wait_until="networkidle", timeout=30000)
        close_overlays(page)

        if args.page_size != 4:
            set_page_size(page, args.page_size)
        else:
            wait_for_page_load(page)

        if args.all:
            total_pages = get_total_pages(page)
            print(f"共 {total_pages} 页，开始遍历截图...")

            for page_num in range(1, total_pages + 1):
                go_to_page(page, page_num)
                inject_footer(page)

                if args.output:
                    filename = os.path.splitext(args.output)[0] + f"_page{page_num}.png"
                else:
                    filename = f"screenshot_page{page_num}.png"

                capture_screenshot(page, filename)
        else:
            if args.page > 1:
                go_to_page(page, args.page)

            inject_footer(page)
            output_file = args.output or "screenshot.png"
            capture_screenshot(page, output_file)

        browser.close()

if __name__ == "__main__":
    main()
