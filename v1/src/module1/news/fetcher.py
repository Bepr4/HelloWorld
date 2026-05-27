# 这个文件实现网页抓取接口；v1 用 urllib 和内存抓取器支撑真实运行与测试。
from __future__ import annotations

import urllib.error
import urllib.request

from module1.models import FetchedPage
from module1.news.extractor import extract_title, strip_html


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
