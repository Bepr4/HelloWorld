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
from module1.news.source_quality import source_quality_issue
from module1.news.text_cleaner import clean_article_text


class UrlLibFetcher:
    """基于标准库 urllib 的最小网页抓取器。

    第一版不做复杂反爬和浏览器渲染，只负责把 URL 取回并抽出文本。
    """

    def __init__(self, user_agent: str = "HelloWorldModule1/0.1", timeout: int = 20) -> None:
        self.user_agent = user_agent
        self.timeout = timeout

    def fetch(self, url: str, query: str | None = None) -> FetchedPage:
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

    def fetch(self, url: str, query: str | None = None) -> FetchedPage:
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
        crawler: Callable[..., Awaitable[Any]] | None = None,
        enable_stealth: bool = True,
        use_undetected_on_block: bool = True,
        headless: bool = True,
        max_retries: int = 1,
        managed_profile_dir: str | Path | None = None,
        proxy: str | None = None,
        enable_bm25_filter: bool = True,
        bm25_threshold: float = 1.0,
        bm25_language: str = "english",
    ) -> None:
        self.user_agent = user_agent
        self.timeout = timeout
        self.base_directory = Path(base_directory) if base_directory is not None else _default_crawl4ai_base_directory()
        self._crawler = crawler
        self.enable_stealth = enable_stealth
        self.use_undetected_on_block = use_undetected_on_block
        self.headless = headless
        self.max_retries = max_retries
        self.managed_profile_dir = Path(managed_profile_dir) if managed_profile_dir else None
        self.proxy = proxy
        self.enable_bm25_filter = enable_bm25_filter
        self.bm25_threshold = bm25_threshold
        self.bm25_language = bm25_language

    def fetch(self, url: str, query: str | None = None) -> FetchedPage:
        """用 Crawl4AI 抓取 URL，并把失败原因保留到 FetchedPage.error。"""

        try:
            result = _run_async(self._crawl(url, query=query))
        except Exception as exc:
            error = f"{exc.__class__.__name__}: {exc}"
            return FetchedPage(url=url, status=_status_from_error(error), error=error)

        return self._result_to_page(url, result)

    async def _crawl(self, url: str, query: str | None = None) -> Any:
        if self._crawler is not None:
            return await _call_crawler(self._crawler, url, query=query)

        self._prepare_runtime_directory()
        try:
            import crawl4ai.async_webcrawler as crawl4ai_webcrawler
            from crawl4ai import (
                AsyncWebCrawler,
                BrowserConfig,
                CacheMode,
                CrawlerRunConfig,
                DefaultMarkdownGenerator,
                ProxyConfig,
            )
            from crawl4ai.content_filter_strategy import BM25ContentFilter, PruningContentFilter
        except ImportError as exc:
            raise RuntimeError("crawl4ai is not installed. Install project dependencies before running fetch_url.") from exc
        _disable_crawl4ai_robots_db(crawl4ai_webcrawler)

        content_filter = self._build_content_filter(
            query=query,
            BM25ContentFilter=BM25ContentFilter,
            PruningContentFilter=PruningContentFilter,
        )
        markdown_generator = _make_config(
            DefaultMarkdownGenerator,
            content_filter=content_filter,
            options={"ignore_links": True, "escape_html": False},
            content_source="cleaned_html",
        )
        run_config = _make_config(
            CrawlerRunConfig,
            verbose=False,
            cache_mode=CacheMode.BYPASS,
            markdown_generator=markdown_generator,
            word_count_threshold=20,
            excluded_tags=["script", "style", "nav", "footer", "form", "aside"],
            excluded_selector="header, footer, nav, aside, [role='navigation'], [aria-label*='share']",
            exclude_external_links=True,
            exclude_social_media_links=True,
            exclude_external_images=True,
            remove_forms=True,
            remove_overlay_elements=True,
            remove_consent_popups=True,
            page_timeout=self.timeout * 1000,
            delay_before_return_html=1.0,
            wait_until="domcontentloaded",
            magic=True,
            simulate_user=True,
            override_navigator=True,
            max_retries=self.max_retries,
            proxy_config=_proxy_config(self.proxy, ProxyConfig),
        )

        normal = await self._crawl_once(
            url,
            AsyncWebCrawler=AsyncWebCrawler,
            BrowserConfig=BrowserConfig,
            run_config=run_config,
            enable_stealth=False,
            use_undetected=False,
        )
        if not _is_blocked_result(normal):
            return normal
        if not _should_retry_blocked_result(normal):
            return normal

        if self.enable_stealth:
            stealth = await self._crawl_once(
                url,
                AsyncWebCrawler=AsyncWebCrawler,
                BrowserConfig=BrowserConfig,
                run_config=run_config,
                enable_stealth=True,
                use_undetected=False,
            )
            if not _is_blocked_result(stealth):
                return stealth
            if not _should_retry_blocked_result(stealth):
                return stealth
            normal = stealth

        if self.use_undetected_on_block:
            try:
                undetected = await self._crawl_once(
                    url,
                    AsyncWebCrawler=AsyncWebCrawler,
                    BrowserConfig=BrowserConfig,
                    run_config=run_config,
                    enable_stealth=self.enable_stealth,
                    use_undetected=True,
                )
            except Exception:
                return normal
            return undetected

        return normal

    def _build_content_filter(
        self,
        *,
        query: str | None,
        BM25ContentFilter: type,
        PruningContentFilter: type,
    ) -> Any:
        """有事件查询时用 BM25 保留相关段落，否则沿用通用 Pruning 清洗。"""

        normalized_query = (query or "").strip()
        if self.enable_bm25_filter and normalized_query:
            return _make_config(
                BM25ContentFilter,
                user_query=normalized_query,
                bm25_threshold=self.bm25_threshold,
                language=self.bm25_language,
            )
        return _make_config(
            PruningContentFilter,
            threshold=0.5,
            threshold_type="dynamic",
            min_word_threshold=40,
        )

    async def _crawl_once(
        self,
        url: str,
        *,
        AsyncWebCrawler: type,
        BrowserConfig: type,
        run_config: Any,
        enable_stealth: bool,
        use_undetected: bool,
    ) -> Any:
        """运行一次 Crawl4AI 抓取；必要时使用官方 UndetectedAdapter。"""

        browser_config = _make_config(
            BrowserConfig,
            browser_type="chromium",
            headless=self.headless,
            use_managed_browser=bool(self.managed_profile_dir),
            user_data_dir=str(self.managed_profile_dir) if self.managed_profile_dir else None,
            user_agent=self.user_agent,
            ignore_https_errors=True,
            enable_stealth=enable_stealth,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            },
        )

        if use_undetected:
            from crawl4ai import UndetectedAdapter
            from crawl4ai.async_crawler_strategy import AsyncPlaywrightCrawlerStrategy

            crawler_strategy = AsyncPlaywrightCrawlerStrategy(
                browser_config=browser_config,
                browser_adapter=UndetectedAdapter(),
            )
            async with AsyncWebCrawler(crawler_strategy=crawler_strategy, config=browser_config) as crawler:
                return await crawler.arun(url=url, config=run_config)

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
            error = _crawl_error(result)
            return FetchedPage(
                url=final_url,
                title=title,
                published_at=published_at,
                status=_status_from_error(error),
                error=error,
            )

        if _looks_blocked_text(text):
            return FetchedPage(
                url=final_url,
                title=title,
                published_at=published_at,
                status="blocked",
                error="blocked_by_antibot: page content looks like an anti-bot challenge",
            )

        if text:
            quality_issue = source_quality_issue(final_url, title, text)
            if quality_issue:
                return FetchedPage(
                    url=final_url,
                    title=title,
                    text=text,
                    published_at=published_at,
                    status="metadata_only",
                    error=f"low_quality: {quality_issue}",
                )
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


async def _call_crawler(crawler: Callable[..., Awaitable[Any]], url: str, *, query: str | None) -> Any:
    """测试注入的 crawler 如果支持 query，就同步收到 BM25 查询上下文。"""

    try:
        signature = inspect.signature(crawler)
    except (TypeError, ValueError):
        return await crawler(url)
    accepts_query = "query" in signature.parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()
    )
    if accepts_query:
        return await crawler(url, query=query)
    return await crawler(url)


def _make_config(config_cls: type, **kwargs: Any) -> Any:
    """按当前安装的 Crawl4AI 版本过滤配置参数，避免小版本参数差异导致启动失败。"""

    try:
        return config_cls(**kwargs)
    except TypeError:
        signature = inspect.signature(config_cls)
        accepted = {name for name in signature.parameters if name != "self"}
        return config_cls(**{key: value for key, value in kwargs.items() if key in accepted})


def _proxy_config(proxy: str | None, ProxyConfig: type) -> Any:
    """从环境配置解析 Crawl4AI proxy_config；支持 direct 和逗号分隔代理链。"""

    if not proxy:
        return None
    items = [item.strip() for item in proxy.split(",") if item.strip()]
    if not items:
        return None
    parsed = []
    for item in items:
        if item.lower() == "direct":
            parsed.append(getattr(ProxyConfig, "DIRECT", "direct"))
        elif hasattr(ProxyConfig, "from_string"):
            parsed.append(ProxyConfig.from_string(item))
        else:
            parsed.append(item)
    return parsed[0] if len(parsed) == 1 else parsed


def _is_blocked_result(result: Any) -> bool:
    """根据 Crawl4AI 返回值判断是否遇到反爬阻断。"""

    if getattr(result, "success", False) and not _looks_blocked_text(_extract_crawl_text(result) or ""):
        return False
    return _is_anti_bot_error(_crawl_error(result)) or _looks_blocked_text(_extract_crawl_text(result) or "")


def _should_retry_blocked_result(result: Any) -> bool:
    """明确的站点临时限制页不继续重试，避免连续触发更重的风控。"""

    text = _extract_crawl_text(result) or ""
    return not _looks_temporary_restricted_text(text)


def _status_from_error(error: str) -> str:
    return "blocked" if _is_anti_bot_error(error) else "failed"


def _is_anti_bot_error(error: str) -> bool:
    lowered = error.lower()
    return any(
        marker in lowered
        for marker in [
            "datadome",
            "captcha",
            "anti-bot",
            "antibot",
            "cloudflare",
            "access denied",
            "access is temporarily restricted",
            "perimeterx",
            "blocked by",
            "bot detection",
            "challenge page",
        ]
    )


def _looks_blocked_text(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in [
            "datadome captcha",
            "enable javascript and cookies",
            "checking your browser",
            "just a moment",
            "verify you are human",
            "access denied",
            "unusual traffic",
            "unusual activity from your device or network",
            "access is temporarily restricted",
            "automated (bot) activity",
            "use of developer or inspection tools",
        ]
    )


def _looks_temporary_restricted_text(text: str) -> bool:
    """识别 Reuters 这类已经临时限制身份的页面，和普通验证码挑战区分开。"""

    lowered = text.lower()
    return any(
        marker in lowered
        for marker in [
            "access is temporarily restricted",
            "unusual activity from your device or network",
            "automated (bot) activity",
        ]
    )


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
