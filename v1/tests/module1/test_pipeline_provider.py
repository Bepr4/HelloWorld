# 这个测试文件验证模块一会把 web_search 配置解析成真正的网页搜索 provider，并把真实抓取切到 Crawl4AI。
from module1.pipeline import _build_fetcher, _build_search_provider
from module1.settings import Module1Settings
from module1.news.fetcher import Crawl4AIFetcher
from module1.news.search_providers import TavilySearchProvider, WebSearchProvider


def test_pipeline_builds_web_search_provider():
    settings = Module1Settings(
        llm_provider="fake",
        search_provider="web_search",
        search_api_key="test-search-key",
        brave_search_endpoint="https://api.search.brave.com/res/v1/web/search",
    )

    provider = _build_search_provider(settings)

    assert isinstance(provider, TavilySearchProvider)


def test_pipeline_builds_brave_provider_when_requested():
    settings = Module1Settings(
        llm_provider="fake",
        search_provider="brave",
        search_api_key="test-search-key",
        brave_search_endpoint="https://api.search.brave.com/res/v1/web/search",
    )

    provider = _build_search_provider(settings)

    assert isinstance(provider, WebSearchProvider)


def test_pipeline_builds_crawl4ai_fetcher_for_real_search_provider():
    settings = Module1Settings(
        llm_provider="fake",
        search_provider="web_search",
        search_api_key="test-search-key",
    )

    fetcher = _build_fetcher(settings)

    assert isinstance(fetcher, Crawl4AIFetcher)


def test_pipeline_passes_crawl4ai_options_to_fetcher():
    settings = Module1Settings(
        llm_provider="fake",
        search_provider="web_search",
        search_api_key="test-search-key",
        crawl4ai_enable_stealth=False,
        crawl4ai_use_undetected=True,
        crawl4ai_headless=False,
        crawl4ai_max_retries=2,
        crawl4ai_profile_dir="tmp/tests/profile",
        crawl4ai_proxy="direct,http://proxy.example.com:8080",
    )

    fetcher = _build_fetcher(settings)

    assert isinstance(fetcher, Crawl4AIFetcher)
    assert fetcher.enable_stealth is False
    assert fetcher.use_undetected_on_block is True
    assert fetcher.headless is False
    assert fetcher.max_retries == 2
    assert str(fetcher.managed_profile_dir).replace("\\", "/") == "tmp/tests/profile"
    assert fetcher.proxy == "direct,http://proxy.example.com:8080"
