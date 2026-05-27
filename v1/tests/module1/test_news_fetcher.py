# 这个测试文件验证网页抓取器在外部网页超时、Crawl4AI 失败或正文转换时不会打断整个模块一流程。
import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request

from module1.news.fetcher import Crawl4AIFetcher, UrlLibFetcher, _disable_crawl4ai_robots_db


def test_url_lib_fetcher_treats_timeout_as_failed_page(monkeypatch):
    def fake_urlopen(request: Request, timeout: int):
        raise TimeoutError("timed out")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    fetcher = UrlLibFetcher(timeout=3)

    page = fetcher.fetch("https://www.reuters.com/world/example")

    assert page.status == "failed"
    assert page.error == "timed out"


def test_crawl4ai_fetcher_maps_markdown_result_to_fetched_page():
    async def fake_crawler(url: str):
        return SimpleNamespace(
            url=url,
            success=True,
            markdown=SimpleNamespace(
                fit_markdown="Reuters reported the latest development.",
                raw_markdown="Navigation that should not be preferred.",
            ),
            metadata={
                "title": "Reuters title",
                "article:published_time": "2026-01-01T00:00:00Z",
            },
        )

    fetcher = Crawl4AIFetcher(crawler=fake_crawler)

    page = fetcher.fetch("https://www.reuters.com/world/example")

    assert page.status == "success"
    assert page.title == "Reuters title"
    assert page.published_at == "2026-01-01T00:00:00Z"
    assert page.text == "Reuters reported the latest development."


def test_crawl4ai_fetcher_records_failed_crawl_error():
    async def fake_crawler(url: str):
        return SimpleNamespace(
            url=url,
            success=False,
            status_code=401,
            error_message="HTTP Forbidden",
            metadata={"title": "Reuters title"},
        )

    fetcher = Crawl4AIFetcher(crawler=fake_crawler)

    page = fetcher.fetch("https://www.reuters.com/world/example")

    assert page.status == "failed"
    assert page.title == "Reuters title"
    assert page.error == "HTTP 401: HTTP Forbidden"


def test_crawl4ai_fetcher_prepares_project_runtime_directory(monkeypatch):
    monkeypatch.delenv("CRAWL4_AI_BASE_DIRECTORY", raising=False)
    base_directory = Path("data/module1/crawl4ai_test_runtime")
    fetcher = Crawl4AIFetcher(base_directory=base_directory)

    runtime_dir = fetcher._prepare_runtime_directory()

    assert runtime_dir == base_directory.resolve()
    assert os.environ["CRAWL4_AI_BASE_DIRECTORY"] == str(base_directory.resolve())
    assert (base_directory / ".crawl4ai" / ".crawl4ai" / "robots").is_dir()


def test_crawl4ai_fetcher_disables_robots_sqlite_cache():
    crawl4ai_webcrawler = SimpleNamespace(RobotsParser=object)

    _disable_crawl4ai_robots_db(crawl4ai_webcrawler)

    parser = crawl4ai_webcrawler.RobotsParser()
    assert asyncio.run(parser.can_fetch("https://www.bbc.com/news")) is True
