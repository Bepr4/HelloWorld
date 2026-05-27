# 这个文件实现真实新闻发现入口：RSS 源采集和 Brave Search API 站内搜索。
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from module1.models import SearchResult


@dataclass(frozen=True)
class NewsFeed:
    """一条 RSS/Atom 新闻源配置。"""

    domain: str
    feed_url: str
    language: str | None = None


class CompositeSearchProvider:
    """组合多个搜索服务，按 URL 去重后返回统一 SearchResult。"""

    def __init__(self, providers: list[object]) -> None:
        self.providers = providers

    def search(self, queries: list[str]) -> list[SearchResult]:
        results: list[SearchResult] = []
        for provider in self.providers:
            try:
                results.extend(provider.search(queries))
            except (TimeoutError, OSError, urllib.error.URLError):
                continue
        return _dedupe_results(results)


class RssSearchProvider:
    """真实 RSS/Atom 采集器。

    它不会把 RSS 当作可信裁判，只负责从配置好的权威来源订阅流里发现候选 URL。
    """

    def __init__(
        self,
        feeds: list[NewsFeed],
        *,
        user_agent: str = "HelloWorldModule1/0.1",
        timeout: int = 20,
        max_items_per_feed: int = 50,
    ) -> None:
        self.feeds = feeds
        self.user_agent = user_agent
        self.timeout = timeout
        self.max_items_per_feed = max_items_per_feed
        self._cache: dict[str, list[SearchResult]] = {}

    @classmethod
    def from_yaml(
        cls,
        path: str | Path,
        *,
        user_agent: str = "HelloWorldModule1/0.1",
        timeout: int = 20,
        max_items_per_feed: int = 50,
    ) -> "RssSearchProvider":
        """从 configs/module1/news_feeds.yaml 读取 RSS 源。"""

        feeds = _parse_feeds_yaml(Path(path).read_text(encoding="utf-8"))
        return cls(feeds, user_agent=user_agent, timeout=timeout, max_items_per_feed=max_items_per_feed)

    def search(self, queries: list[str]) -> list[SearchResult]:
        """对每个 query 在 RSS 条目中做轻量关键词匹配。"""

        results: list[SearchResult] = []
        for query in queries:
            domain = _extract_site_domain(query)
            terms = _extract_query_terms(query)
            for feed in self._feeds_for_domain(domain):
                for result in self._read_feed(feed):
                    haystack = " ".join([result.title or "", result.snippet or "", result.url]).lower()
                    if _matches_terms(haystack, terms):
                        results.append(result)
        return _dedupe_results(results)

    def _feeds_for_domain(self, domain: str | None) -> list[NewsFeed]:
        if not domain:
            return self.feeds
        normalized = domain.lower().removeprefix("www.")
        return [feed for feed in self.feeds if _same_or_subdomain(feed.domain, normalized)]

    def _read_feed(self, feed: NewsFeed) -> list[SearchResult]:
        if feed.feed_url not in self._cache:
            self._cache[feed.feed_url] = self._fetch_feed(feed)
        return self._cache[feed.feed_url]

    def _fetch_feed(self, feed: NewsFeed) -> list[SearchResult]:
        request = urllib.request.Request(feed.feed_url, headers={"User-Agent": self.user_agent})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except (urllib.error.URLError, TimeoutError, OSError):
            return []
        return _parse_feed(raw, max_items=self.max_items_per_feed)


class BraveSearchProvider:
    """Brave Search API 搜索器。

    Brave 官方要求用 X-Subscription-Token 请求头传 API key。
    """

    def __init__(
        self,
        api_key: str,
        *,
        endpoint: str = "https://api.search.brave.com/res/v1/web/search",
        timeout: int = 20,
        count: int = 10,
    ) -> None:
        self.api_key = api_key
        self.endpoint = endpoint
        self.timeout = timeout
        self.count = count

    def search(self, queries: list[str]) -> list[SearchResult]:
        results: list[SearchResult] = []
        for query in queries:
            results.extend(self._search_one(query))
        return _dedupe_results(results)

    def _search_one(self, query: str) -> list[SearchResult]:
        params = urllib.parse.urlencode({"q": query, "count": self.count})
        separator = "&" if "?" in self.endpoint else "?"
        url = f"{self.endpoint}{separator}{params}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": self.api_key,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            return []
        return _parse_brave_results(data)


class WebSearchProvider(BraveSearchProvider):
    """web_search 工具的默认真实搜索实现。
    这个类保留给 Brave 兼容路径；默认 web_search 已切到 TavilySearchProvider。
    """


class TavilySearchProvider:
    """Tavily Search API 搜索器。
    LLM 调用 web_search 时，后端会把 query 发给 Tavily，再把结构化搜索结果转成统一的 SearchResult。
    """

    def __init__(
        self,
        api_key: str,
        *,
        endpoint: str = "https://api.tavily.com/search",
        timeout: int = 20,
        count: int = 10,
        search_depth: str = "basic",
    ) -> None:
        self.api_key = api_key
        self.endpoint = endpoint
        self.timeout = timeout
        self.count = count
        self.search_depth = search_depth

    def search(self, queries: list[str]) -> list[SearchResult]:
        results: list[SearchResult] = []
        for query in queries:
            results.extend(self._search_one(query))
        return _dedupe_results(results)

    def _search_one(self, query: str) -> list[SearchResult]:
        payload = {
            "query": query,
            "max_results": self.count,
            "search_depth": self.search_depth,
        }
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            return []
        return _parse_tavily_results(data)


def _parse_tavily_results(data: dict) -> list[SearchResult]:
    """从 Tavily Search 返回体中提取统一 SearchResult。"""

    results: list[SearchResult] = []
    for item in data.get("results", []):
        if not isinstance(item, dict) or not item.get("url"):
            continue
        results.append(
            SearchResult(
                url=item["url"],
                title=item.get("title"),
                snippet=item.get("content") or item.get("snippet"),
                published_at=item.get("published_date"),
                discovery_method="tavily_search",
            )
        )
    return _dedupe_results(results)


def _parse_brave_results(data: dict) -> list[SearchResult]:
    """从 Brave web/news 结果中提取统一 SearchResult。"""

    results: list[SearchResult] = []
    for section_name in ["web", "news"]:
        section = data.get(section_name) or {}
        for item in section.get("results", []):
            if not isinstance(item, dict) or not item.get("url"):
                continue
            results.append(
                SearchResult(
                    url=item["url"],
                    title=item.get("title"),
                    snippet=item.get("description") or item.get("snippet"),
                    published_at=item.get("age") or item.get("page_age"),
                    discovery_method="brave_search",
                )
            )
    return _dedupe_results(results)


def _parse_feed(raw: bytes, *, max_items: int) -> list[SearchResult]:
    """解析 RSS 2.0 或 Atom 条目。"""

    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []

    if _local_name(root.tag) == "feed":
        entries = root.findall("{*}entry")
        results: list[SearchResult] = []
        for entry in entries[:max_items]:
            result = _atom_entry_to_result(entry)
            if result:
                results.append(result)
        return results

    items = root.findall(".//item")
    results = []
    for item in items[:max_items]:
        result = _rss_item_to_result(item)
        if result:
            results.append(result)
    return results


def _rss_item_to_result(item: ET.Element) -> SearchResult | None:
    title = _child_text(item, "title")
    link = _child_text(item, "link")
    if not link:
        return None
    return SearchResult(
        url=link,
        title=title,
        snippet=_child_text(item, "description") or _child_text(item, "summary"),
        published_at=_child_text(item, "pubDate"),
        discovery_method="rss_feed",
    )


def _atom_entry_to_result(entry: ET.Element) -> SearchResult | None:
    title = _child_text(entry, "title")
    link = _atom_link(entry)
    if not link:
        return None
    return SearchResult(
        url=link,
        title=title,
        snippet=_child_text(entry, "summary") or _child_text(entry, "content"),
        published_at=_child_text(entry, "updated") or _child_text(entry, "published"),
        discovery_method="rss_feed",
    )


def _child_text(parent: ET.Element, child_name: str) -> str | None:
    for child in list(parent):
        if _local_name(child.tag) == child_name:
            text = "".join(child.itertext()).strip()
            return text or None
    return None


def _atom_link(entry: ET.Element) -> str | None:
    for child in list(entry):
        if _local_name(child.tag) != "link":
            continue
        href = child.attrib.get("href")
        rel = child.attrib.get("rel", "alternate")
        if href and rel == "alternate":
            return href
    return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _extract_site_domain(query: str) -> str | None:
    match = re.search(r"\bsite:([^\s]+)", query, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip().lower().removeprefix("www.")


def _extract_query_terms(query: str) -> list[str]:
    cleaned = re.sub(r"\bsite:[^\s]+", " ", query, flags=re.IGNORECASE)
    cleaned = cleaned.replace('"', " ").replace("'", " ")
    tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9][A-Za-z0-9_-]{2,}", cleaned)
    stopwords = {
        "and",
        "the",
        "for",
        "with",
        "from",
        "this",
        "that",
        "news",
        "latest",
        "conflict",
        "event",
    }
    return [token.lower() for token in tokens if token.lower() not in stopwords][:12]


def _matches_terms(haystack: str, terms: list[str]) -> bool:
    if not terms:
        return True
    return any(term in haystack for term in terms)


def _same_or_subdomain(source_domain: str, query_domain: str) -> bool:
    source = source_domain.lower().removeprefix("www.")
    query = query_domain.lower().removeprefix("www.")
    return source == query or source.endswith(f".{query}") or query.endswith(f".{source}")


def _dedupe_results(results: list[SearchResult]) -> list[SearchResult]:
    seen: set[str] = set()
    output: list[SearchResult] = []
    for result in results:
        key = result.url.lower().rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        output.append(result)
    return output


def _parse_feeds_yaml(text: str) -> list[NewsFeed]:
    feeds: list[dict] = []
    current: dict | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line == "feeds:":
            continue
        if line.startswith("- "):
            if current:
                feeds.append(current)
            current = {}
            line = line[2:].strip()
            if line:
                key, value = line.split(":", 1)
                current[key.strip()] = value.strip().strip('"').strip("'")
            continue
        if current is not None and ":" in line:
            key, value = line.split(":", 1)
            current[key.strip()] = value.strip().strip('"').strip("'")

    if current:
        feeds.append(current)
    return [NewsFeed(**feed) for feed in feeds]
