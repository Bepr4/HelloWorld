# 这个测试文件验证网页抓取器在外部网页超时、Crawl4AI 失败或正文转换时不会打断整个模块一流程。
import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request

from module1.news.fetcher import (
    Crawl4AIFetcher,
    UrlLibFetcher,
    _disable_crawl4ai_robots_db,
    _should_retry_blocked_result,
)


def test_url_lib_fetcher_treats_timeout_as_failed_page(monkeypatch):
    def fake_urlopen(request: Request, timeout: int):
        raise TimeoutError("timed out")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    fetcher = UrlLibFetcher(timeout=3)

    page = fetcher.fetch("https://www.reuters.com/world/example")

    assert page.status == "failed"
    assert page.error == "timed out"


def test_crawl4ai_fetcher_maps_markdown_result_to_fetched_page():
    article_text = (
        "Reuters reported the latest development after officials held emergency meetings and regional governments "
        "urged both sides to avoid additional escalation. Diplomats said the talks focused on keeping maritime routes "
        "open while military commanders reviewed defensive deployments across the region and briefed allied governments "
        "about possible risks to shipping, energy supplies, and civilian flights.\n\n"
        "The report added that analysts were watching whether public threats would translate into action, while energy "
        "markets and neighboring states prepared for further uncertainty over the coming days. Officials said the next "
        "round of contacts would test whether both governments could preserve a fragile diplomatic channel."
    )

    async def fake_crawler(url: str):
        return SimpleNamespace(
            url=url,
            success=True,
            markdown=SimpleNamespace(
                fit_markdown=article_text,
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
    assert page.text == article_text
    assert page.raw_markdown == "Navigation that should not be preferred."
    assert page.fit_markdown == article_text
    assert page.cleaned_text == article_text


def test_crawl4ai_fetcher_preserves_fit_markdown_and_cleaned_text_separately():
    raw_markdown = "Navigation and unrelated page chrome before the article."
    fit_markdown = """
Diplomats said the latest talks were focused on protecting civilians and keeping channels open after a week of strikes and warnings across the region, while military officials reviewed reports from several front-line areas and briefed allied governments about risks to energy infrastructure and shipping routes.

Officials added that allied governments were comparing battlefield reports, sanctions options, and possible diplomatic guarantees before another round of meetings, with negotiators trying to preserve a fragile channel for emergency communication and reduce the chance that local incidents could expand into a wider confrontation.

List of IAB Vendors
Use precise geolocation data
Actively scan device characteristics for identification
I Reject All
Confirm My Choices
"""

    async def fake_crawler(url: str):
        return SimpleNamespace(
            url=url,
            success=True,
            markdown=SimpleNamespace(
                fit_markdown=fit_markdown,
                raw_markdown=raw_markdown,
            ),
            metadata={"title": "Reuters title"},
        )

    fetcher = Crawl4AIFetcher(crawler=fake_crawler)

    page = fetcher.fetch("https://www.reuters.com/world/example")

    assert page.status == "success"
    assert page.raw_markdown == raw_markdown
    assert "List of IAB Vendors" in page.fit_markdown
    assert "List of IAB Vendors" not in page.cleaned_text
    assert page.text == page.cleaned_text


def test_crawl4ai_fetcher_passes_bm25_query_to_injected_crawler():
    captured = {}

    async def fake_crawler(url: str, query: str | None = None):
        captured["query"] = query
        return SimpleNamespace(
            url=url,
            success=True,
            markdown=SimpleNamespace(
                fit_markdown=(
                    "Reuters reported the latest development after officials held emergency meetings and regional governments "
                    "urged both sides to avoid additional escalation. Diplomats said the talks focused on keeping maritime routes "
                    "open while military commanders reviewed defensive deployments across the region and briefed allied governments "
                    "about possible risks to shipping, energy supplies, and civilian flights.\n\n"
                    "The report added that analysts were watching whether public threats would translate into action, while energy "
                    "markets and neighboring states prepared for further uncertainty over the coming days. Officials said the next "
                    "round of contacts would test whether both governments could preserve a fragile diplomatic channel."
                ),
                raw_markdown="Navigation that should not be preferred.",
            ),
            metadata={"title": "Reuters title"},
        )

    fetcher = Crawl4AIFetcher(crawler=fake_crawler)

    page = fetcher.fetch("https://www.reuters.com/world/example", query="US Iran conflict Strait of Hormuz")

    assert page.status == "success"
    assert captured["query"] == "US Iran conflict Strait of Hormuz"


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


def test_crawl4ai_fetcher_marks_datadome_as_blocked():
    async def fake_crawler(url: str):
        return SimpleNamespace(
            url=url,
            success=False,
            status_code=401,
            error_message="Blocked by anti-bot protection: DataDome captcha",
            metadata={"title": "Reuters title"},
        )

    fetcher = Crawl4AIFetcher(crawler=fake_crawler)

    page = fetcher.fetch("https://www.reuters.com/world/example")

    assert page.status == "blocked"
    assert "DataDome captcha" in page.error


def test_crawl4ai_fetcher_marks_reuters_temporary_restriction_as_blocked():
    async def fake_crawler(url: str):
        return SimpleNamespace(
            url=url,
            success=True,
            markdown=SimpleNamespace(
                fit_markdown=(
                    "We detected unusual activity from your device or network.\n\n"
                    "Reasons may include:\n"
                    "- Rapid taps or clicks\n"
                    "- JavaScript disabled or not working\n"
                    "- Automated (bot) activity on your network\n"
                    "- Use of developer or inspection tools\n\n"
                    "Access is temporarily restricted"
                ),
                raw_markdown="",
            ),
            metadata={"title": "Access is temporarily restricted"},
        )

    fetcher = Crawl4AIFetcher(crawler=fake_crawler)

    page = fetcher.fetch("https://www.reuters.com/world/example")

    assert page.status == "blocked"
    assert page.error == "blocked_by_antibot: page content looks like an anti-bot challenge"


def test_crawl4ai_fetcher_does_not_retry_temporary_restriction():
    result = SimpleNamespace(
        success=True,
        markdown=SimpleNamespace(
            fit_markdown="Access is temporarily restricted because we detected unusual activity from your device or network.",
            raw_markdown="",
        ),
    )

    assert _should_retry_blocked_result(result) is False


def test_crawl4ai_fetcher_downgrades_topic_pages_to_metadata_only():
    async def fake_crawler(url: str):
        return SimpleNamespace(
            url=url,
            success=True,
            markdown=SimpleNamespace(
                fit_markdown=(
                    "# Iran war\n"
                    "FollowFollowFollowingFollowingUnfollowUnfollow\n"
                    "You are now following Iran war\n"
                    "Updates from your News topics will appear in My News.\n"
                ),
                raw_markdown="",
            ),
            metadata={"title": "US-Israel war with Iran | Latest News and Updates - BBC"},
        )

    fetcher = Crawl4AIFetcher(crawler=fake_crawler)

    page = fetcher.fetch("https://www.bbc.com/news/topics/cx2jyv8j8gwt")

    assert page.status == "metadata_only"
    assert page.error == "low_quality: index_or_topic_page"


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
