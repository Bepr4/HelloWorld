# 这个测试文件验证真实搜索 provider 的请求格式和 RSS 解析逻辑，不依赖外网。
import json
from urllib.request import Request

from module1.models import SearchResult
from module1.news.search_providers import (
    BraveSearchProvider,
    CompositeSearchProvider,
    NewsFeed,
    RssSearchProvider,
    TavilySearchProvider,
    WebSearchProvider,
)


def test_rss_search_provider_parses_and_filters_feed(monkeypatch):
    rss = b"""
<rss>
  <channel>
    <item>
      <title>Iran strike prompts international reaction</title>
      <link>https://www.bbc.com/news/world-middle-east-1</link>
      <description>Officials responded after a strike involving Iran.</description>
      <pubDate>Wed, 01 Jan 2026 00:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Sports update</title>
      <link>https://www.bbc.com/sport/1</link>
      <description>Unrelated story.</description>
    </item>
  </channel>
</rss>
"""

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return rss

    def fake_urlopen(request: Request, timeout: int):
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = RssSearchProvider(
        [NewsFeed(domain="bbc.com", feed_url="https://feeds.bbci.co.uk/news/world/rss.xml")],
    )

    results = provider.search(["site:bbc.com Iran strike"])

    assert len(results) == 1
    assert results[0].url == "https://www.bbc.com/news/world-middle-east-1"
    assert results[0].title == "Iran strike prompts international reaction"


def test_rss_search_provider_treats_timeout_as_empty_result(monkeypatch):
    def fake_urlopen(request: Request, timeout: int):
        raise TimeoutError("timed out")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = RssSearchProvider(
        [NewsFeed(domain="bbc.com", feed_url="https://feeds.bbci.co.uk/news/world/rss.xml")],
    )

    assert provider.search(["site:bbc.com Iran strike"]) == []


def test_brave_search_provider_uses_subscription_token(monkeypatch):
    captured: dict = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(
                {
                    "web": {
                        "results": [
                            {
                                "url": "https://www.reuters.com/world/example",
                                "title": "Reuters title",
                                "description": "Reuters snippet",
                            }
                        ]
                    }
                }
            ).encode("utf-8")

    def fake_urlopen(request: Request, timeout: int):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.headers)
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = BraveSearchProvider("test-search-key", endpoint="https://api.search.brave.com/res/v1/web/search", timeout=8)

    results = provider.search(["site:reuters.com Iran strike"])

    normalized_headers = {key.lower(): value for key, value in captured["headers"].items()}
    assert "q=site%3Areuters.com+Iran+strike" in captured["url"]
    assert normalized_headers["x-subscription-token"] == "test-search-key"
    assert captured["timeout"] == 8
    assert results[0].url == "https://www.reuters.com/world/example"


def test_web_search_provider_reuses_brave_api_shape(monkeypatch):
    captured: dict = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(
                {
                    "web": {
                        "results": [
                            {
                                "url": "https://www.bbc.com/news/world-middle-east-1",
                                "title": "BBC title",
                                "description": "BBC snippet",
                            }
                        ]
                    }
                }
            ).encode("utf-8")

    def fake_urlopen(request: Request, timeout: int):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.headers)
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = WebSearchProvider("test-search-key", endpoint="https://api.search.brave.com/res/v1/web/search")

    results = provider.search(["site:bbc.com Soleimani killed January 2020"])

    normalized_headers = {key.lower(): value for key, value in captured["headers"].items()}
    assert "q=site%3Abbc.com+Soleimani+killed+January+2020" in captured["url"]
    assert normalized_headers["x-subscription-token"] == "test-search-key"
    assert results[0].discovery_method == "brave_search"
    assert results[0].url == "https://www.bbc.com/news/world-middle-east-1"


def test_tavily_search_provider_uses_bearer_auth(monkeypatch):
    captured: dict = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(
                {
                    "results": [
                        {
                            "url": "https://www.reuters.com/world/middle-east/example",
                            "title": "Reuters title",
                            "content": "Reuters Tavily snippet",
                            "published_date": "2020-01-03",
                        }
                    ]
                }
            ).encode("utf-8")

    def fake_urlopen(request: Request, timeout: int):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.headers)
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = TavilySearchProvider("test-search-key", endpoint="https://api.tavily.com/search", timeout=7, count=3)

    results = provider.search(["site:reuters.com Soleimani killed January 2020"])

    assert captured["url"] == "https://api.tavily.com/search"
    assert captured["headers"]["Authorization"] == "Bearer test-search-key"
    assert captured["payload"] == {
        "query": "site:reuters.com Soleimani killed January 2020",
        "max_results": 3,
        "search_depth": "basic",
    }
    assert captured["timeout"] == 7
    assert results[0].url == "https://www.reuters.com/world/middle-east/example"
    assert results[0].snippet == "Reuters Tavily snippet"
    assert results[0].published_at == "2020-01-03"
    assert results[0].discovery_method == "tavily_search"


def test_composite_search_provider_skips_failed_provider():
    class FailingProvider:
        def search(self, queries: list[str]):
            raise TimeoutError("timed out")

    class WorkingProvider:
        def search(self, queries: list[str]):
            return [SearchResult(url="https://www.reuters.com/world/example", title="Reuters title")]

    provider = CompositeSearchProvider([FailingProvider(), WorkingProvider()])

    results = provider.search(["Iran strike"])

    assert len(results) == 1
    assert results[0].url == "https://www.reuters.com/world/example"
