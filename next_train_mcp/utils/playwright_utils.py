import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from loguru import logger

# 使用同步 Playwright API（在独立线程中运行），
# 避免 uvicorn 事件循环不支持子进程的问题（Windows）。

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pw")

# ── 全局共享同步浏览器 ─────────────────────────────────────────────────

_browser_sync: Any = None  # playwright.sync_api.Browser
_browser_lock: Any = None
_playwright_sync: Any = None


def _get_browser_lock():
    global _browser_lock
    if _browser_lock is None:
        import threading
        _browser_lock = threading.Lock()
    return _browser_lock


def _start_browser_sync():
    """同步方式启动浏览器（在 worker 线程中调用）。"""
    global _playwright_sync, _browser_sync
    from playwright.sync_api import sync_playwright

    if _browser_sync is not None:
        try:
            _browser_sync.contexts  # 检查是否还活着
            return _browser_sync
        except Exception:
            pass
    with _get_browser_lock():
        if _browser_sync is not None:
            try:
                _browser_sync.contexts
                return _browser_sync
            except Exception:
                pass
        if _playwright_sync is None:
            _playwright_sync = sync_playwright().start()
        _browser_sync = _playwright_sync.chromium.launch(headless=False)
        logger.info("Shared Playwright browser (sync) launched")
        return _browser_sync


def _fetch_page_text_sync(
        url: str,
        wait_until: str = "domcontentloaded",
        timeout: int = 30000,
        extra_wait: float = 6.0,
        user_agent: str | None = None,
) -> str:
    """同步方式获取页面文本（在 worker 线程中调用）。"""
    browser = _start_browser_sync()
    context = browser.new_context(
        user_agent=user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1920, "height": 1080},
    )
    page = context.new_page()
    try:
        # 用 "commit" 只等首字节响应，快速拿到页面再等 JS 渲染
        page.goto(url, wait_until="commit", timeout=timeout)
        # 等待页面解析 + JS 执行
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        if extra_wait > 0:
            time.sleep(extra_wait)
        text = page.inner_text("body")
        return text
    finally:
        page.close()
        context.close()


def _fetch_html_sync(
        url: str,
        wait_until: str = "networkidle",
        timeout: int = 30000,
        user_agent: str | None = None,
) -> str:
    """同步方式获取页面 HTML（在 worker 线程中调用）。"""
    browser = _start_browser_sync()
    context = browser.new_context(
        user_agent=user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1920, "height": 1080},
    )
    page = context.new_page()
    try:
        page.goto(url, wait_until=wait_until, timeout=timeout)
        html = page.content()
        return html
    finally:
        page.close()
        context.close()


# ── 公开异步接口 ───────────────────────────────────────────────────────

async def fetch_rendered_html(
        url: str,
        wait_until: str = "networkidle",
        timeout: int = 30000,
        user_agent: str | None = None,
) -> str:
    """
    使用 Playwright 获取网页渲染后的完整 HTML（在后台线程中运行）。
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _executor,
        _fetch_html_sync,
        url,
        wait_until,
        timeout,
        user_agent,
    )


async def fetch_page_text(
        url: str,
        wait_until: str = "domcontentloaded",
        timeout: int = 60000,
        extra_wait: float = 5.0,
        user_agent: str | None = None,
) -> str:
    """
    使用 Playwright 获取网页渲染后的可见文本（在后台线程中运行）。
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _executor,
        _fetch_page_text_sync,
        url,
        wait_until,
        timeout,
        extra_wait,
        user_agent,
    )


if __name__ == '__main__':
    _fetch_html_sync('https://www.flightview.com/flight-tracker/TK/70?date=2026-07-12')
