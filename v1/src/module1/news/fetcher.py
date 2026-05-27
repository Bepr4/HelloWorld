# 这个文件实现网页正文抓取接口，真实运行优先用 Crawl4AI 抓取动态网页，测试可用内存抓取器注入固定内容。
from __future__ import annotations

import asyncio
import inspect
import os
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
import urllib.error
import urllib.request

from module1.models import FetchedPage
from module1.news.extractor import extract_title, strip_html
from module1.news.text_cleaner import clean_article_text


class UrlLibFetcher:
    """基于标准库 urllib 的最小网页抓取器。

    第一版不做复杂反爬和浏览器渲染，只负责把 URL 取回并抽出文本。
    """

    def __init__(self, user_agent: str = "HelloWorldModule1/0.1", timeout: int = 20) -> None:
        self.user_agent = user_agent
        self.timeout = timeout

    def fetch(self, url: str) -> FetchedPage:
        """抓取一个 URL，并返回 success / metadata_only / failed 三种状态。"""

        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return FetchedPage(url=url, status="failed", error=str(exc))

        text = strip_html(raw)
        title = extract_title(raw)
        if text:
            return FetchedPage(url=url, title=title, text=text, status="success")
        return FetchedPage(url=url, title=title, status="metadata_only")


class InMemoryFetcher:
    """测试用抓取器：URL -> FetchedPage 或正文字符串。"""

    def __init__(self, pages: dict[str, FetchedPage | str]) -> None:
        self.pages = pages

    def fetch(self, url: str) -> FetchedPage:
        value = self.pages.get(url)
        if value is None:
            return FetchedPage(url=url, status="failed", error="not found in in-memory fetcher")
        if isinstance(value, FetchedPage):
            return value
        return FetchedPage(url=url, text=value, status="success")


class Crawl4AIFetcher:
    """基于 Crawl4AI 的真实网页抓取器。

    v1 的 fetch_url 工具仍然只暴露一个同步 fetch(url) 方法；内部用 Crawl4AI 的异步浏览器抓取，
    把 markdown、页面标题和发布时间统一转换成 FetchedPage，方便后续 SourceDocument 落盘。
    """

    def __init__(
        self,
        user_agent: str = "HelloWorldModule1/0.1",
        timeout: int = 20,
        *,
        base_directory: str | Path | None = None,
        crawler: Callable[[str], Awaitable[Any]] | None = None,
    ) -> None:
        self.user_agent = user_agent
        self.timeout = timeout
        self.base_directory = Path(base_directory) if base_directory is not None else _default_crawl4ai_base_directory()
        self._crawler = crawler

    def fetch(self, url: str) -> FetchedPage:
        """用 Crawl4AI 抓取 URL，并把失败原因保留到 FetchedPage.error。"""

        try:
            result = _run_async(self._crawl(url))
        except Exception as exc:
            return FetchedPage(url=url, status="failed", error=f"{exc.__class__.__name__}: {exc}")

        return self._result_to_page(url, result)

    async def _crawl(self, url: str) -> Any:
        if self._crawler is not None:
            return await self._crawler(url)

        self._prepare_runtime_directory()
        try:
            import crawl4ai.async_webcrawler as crawl4ai_webcrawler
            from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
        except ImportError as exc:
            raise RuntimeError("crawl4ai is not installed. Install project dependencies before running fetch_url.") from exc
        _disable_crawl4ai_robots_db(crawl4ai_webcrawler)

        browser_config = _make_config(
            BrowserConfig,
            browser_type="chromium",
            headless=True,
            user_agent=self.user_agent,
            ignore_https_errors=True,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            },
        )
        run_config = _make_config(
            CrawlerRunConfig,
            verbose=False,
            cache_mode=CacheMode.BYPASS,
            word_count_threshold=10,
            excluded_tags=["script", "style", "nav", "footer", "form"],
            exclude_external_links=True,
            exclude_social_media_links=True,
            remove_forms=True,
            remove_overlay_elements=True,
            remove_consent_popups=True,
            page_timeout=self.timeout * 1000,
            delay_before_return_html=1.0,
            wait_until="domcontentloaded",
            magic=True,
            simulate_user=True,
            override_navigator=True,
        )

        # 每次 fetch_url 只抓一个新闻页，独立浏览器上下文便于隔离 Cookie 和页面状态。
        async with AsyncWebCrawler(config=browser_config) as crawler:
            return await crawler.arun(url=url, config=run_config)

    def _prepare_runtime_directory(self) -> Path:
        """把 Crawl4AI 的缓存、robots 数据库固定到项目工作区内，避免沙箱无法写入用户目录。"""

        base_directory = Path(os.environ.get("CRAWL4_AI_BASE_DIRECTORY") or self.base_directory).resolve()
        os.environ.setdefault("CRAWL4_AI_BASE_DIRECTORY", str(base_directory))

        # Crawl4AI 会在 base 下再创建 .crawl4ai；当前版本的 robots 缓存会多嵌一层 .crawl4ai。
        for directory in [
            base_directory,
            base_directory / ".crawl4ai",
            base_directory / ".crawl4ai" / "cache",
            base_directory / ".crawl4ai" / "models",
            base_directory / ".crawl4ai" / ".crawl4ai" / "robots",
        ]:
            directory.mkdir(parents=True, exist_ok=True)
        return base_directory

    def _result_to_page(self, requested_url: str, result: Any) -> FetchedPage:
        final_url = str(getattr(result, "url", None) or requested_url)
        metadata = getattr(result, "metadata", None) if isinstance(getattr(result, "metadata", None), dict) else {}
        title = _metadata_title(metadata) or _title_from_html(result)
        published_at = _metadata_published_at(metadata)
        text = clean_article_text(_extract_crawl_text(result) or "")

        if not getattr(result, "success", False):
            return FetchedPage(
                url=final_url,
                title=title,
                published_at=published_at,
                status="failed",
                error=_crawl_error(result),
            )

        if text:
            return FetchedPage(
                url=final_url,
                title=title,
                text=text,
                published_at=published_at,
                status="success",
            )

        return FetchedPage(
            url=final_url,
            title=title,
            published_at=published_at,
            status="metadata_only",
            error="crawl4ai returned no extractable text",
        )


def _default_crawl4ai_base_directory() -> Path:
    """返回项目内的 Crawl4AI 运行目录，供本地服务和测试共享。"""

    project_root = Path(__file__).resolve().parents[3]
    return project_root / "data" / "module1" / "crawl4ai_runtime"


class _NoopRobotsParser:
    """Crawl4AI 默认未启用 robots 检查时使用的无落盘替代解析器。"""

    async def can_fetch(self, url: str, user_agent: str = "*") -> bool:
        return True


def _disable_crawl4ai_robots_db(crawl4ai_webcrawler: Any) -> None:
    """避免 Crawl4AI 在未启用 robots 检查时仍初始化 SQLite robots 缓存。"""

    crawl4ai_webcrawler.RobotsParser = _NoopRobotsParser


def _run_async(coro: Awaitable[Any]) -> Any:
    """在同步 pipeline 中安全运行 Crawl4AI 的异步抓取协程。"""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001 - 跨线程把异常原样带回主调用栈。
            result["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


def _make_config(config_cls: type, **kwargs: Any) -> Any:
    """按当前安装的 Crawl4AI 版本过滤配置参数，避免小版本参数差异导致启动失败。"""

    try:
        return config_cls(**kwargs)
    except TypeError:
        signature = inspect.signature(config_cls)
        accepted = {name for name in signature.parameters if name != "self"}
        return config_cls(**{key: value for key, value in kwargs.items() if key in accepted})


def _extract_crawl_text(result: Any) -> str | None:
    markdown = getattr(result, "markdown", None)
    candidates = []
    if isinstance(markdown, str):
        candidates.append(markdown)
    elif markdown is not None:
        candidates.extend(
            [
                getattr(markdown, "fit_markdown", None),
                getattr(markdown, "raw_markdown", None),
                getattr(markdown, "markdown_with_citations", None),
            ]
        )

    candidates.extend(
        [
            getattr(result, "extracted_content", None),
            strip_html(getattr(result, "cleaned_html", "") or ""),
            strip_html(getattr(result, "html", "") or ""),
        ]
    )

    for candidate in candidates:
        if isinstance(candidate, str):
            text = candidate.strip()
            if text:
                return text
    return None


def _metadata_title(metadata: dict[str, Any]) -> str | None:
    for key in ["title", "og:title", "twitter:title"]:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _metadata_published_at(metadata: dict[str, Any]) -> str | None:
    for key in ["published_time", "article:published_time", "date", "pubdate", "published"]:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _title_from_html(result: Any) -> str | None:
    for attr in ["cleaned_html", "html"]:
        html = getattr(result, attr, None)
        if isinstance(html, str):
            title = extract_title(html)
            if title:
                return title
    return None


def _crawl_error(result: Any) -> str:
    status_code = getattr(result, "status_code", None)
    message = str(getattr(result, "error_message", None) or "crawl4ai failed")
    if status_code:
        return f"HTTP {status_code}: {message}"
    return message
