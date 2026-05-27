# 这个测试文件验证新闻 Agent 能采集可信来源、丢弃未知来源，并生成时间线修正建议。
from module1.intake.coordinator import Coordinator
from module1.models import FetchedPage, SearchResult, TimelineItem
from module1.news.agent import NewsAgent
from module1.news.fetcher import InMemoryFetcher
from module1.news.source_collector import SourceCollector, StaticSearchProvider
from module1.news.source_registry import SourceEntry, SourceRegistry


def test_news_agent_collects_blocks_and_timeline_suggestions():
    registry = SourceRegistry(
        [
            SourceEntry(domain="reuters.com", source_tier="P1", source_type="wire", language="en"),
            SourceEntry(domain="apnews.com", source_tier="P1", source_type="wire", language="en"),
        ]
    )
    search = StaticSearchProvider(
        [
            SearchResult(
                url="https://www.reuters.com/world/soleimani-jan-3",
                title="Soleimani conflict strike on 2020-01-03",
                published_at="2020-01-03",
            ),
            SearchResult(
                url="https://apnews.com/article/soleimani-ceasefire-jan-04",
                title="Soleimani conflict ceasefire talks on 2020-01-04",
                published_at="2020-01-04",
            ),
            SearchResult(
                url="https://random-blog.example/soleimani",
                title="Unknown blog should be dropped",
                published_at="2020-01-04",
            ),
        ]
    )
    fetcher = InMemoryFetcher(
        {
            "https://www.reuters.com/world/soleimani-jan-3": FetchedPage(
                url="https://www.reuters.com/world/soleimani-jan-3",
                title="Soleimani conflict strike on 2020-01-03",
                text="Soleimani conflict strike on 2020-01-03 involved US and Iran forces.",
                raw_markdown="raw Reuters markdown",
                fit_markdown="fit Reuters markdown",
                cleaned_text="Soleimani conflict strike on 2020-01-03 involved US and Iran forces.",
                published_at="2020-01-03",
                status="success",
            ),
            "https://apnews.com/article/soleimani-ceasefire-jan-04": FetchedPage(
                url="https://apnews.com/article/soleimani-ceasefire-jan-04",
                title="Soleimani conflict ceasefire talks on 2020-01-04",
                text="Soleimani conflict ceasefire talks on 2020-01-04 involved US and Iran officials.",
                published_at="2020-01-04",
                status="success",
            ),
        }
    )
    scope = Coordinator().confirm_scope(
        "Soleimani conflict",
        confirmed_event="Soleimani conflict",
        confirmed_scope="Soleimani conflict",
    )
    baseline = [
        TimelineItem(
            timeline_item_id="tl_001",
            time_type="point",
            start_date="2020-01-03",
            title="Soleimani conflict strike",
            summary="Soleimani conflict strike on 2020-01-03",
            search_keywords=["Soleimani conflict", "strike"],
        ),
        TimelineItem(
            timeline_item_id="tl_002",
            time_type="point",
            start_date="2020-01-08",
            title="Iran missile retaliation",
            summary="Iran missile retaliation on 2020-01-08",
            search_keywords=["missile retaliation"],
        ),
    ]
    task = Coordinator().build_timeline_collection_task(scope, baseline, event_id="event_test")
    agent = NewsAgent(SourceCollector(registry, search), fetcher=fetcher)

    result = agent.run(task)

    assert {doc.publisher for doc in result.source_documents} == {"reuters.com", "apnews.com"}
    assert all("random-blog" not in doc.url for doc in result.source_documents)
    assert any(block.timeline_item_id == "tl_001" for block in result.news_blocks)
    assert result.news_blocks[0].reported_facts
    assert result.timeline_update_suggestions
    assert result.timeline_update_suggestions[0].suggested_start_date == "2020-01-04"
    reuters_doc = next(doc for doc in result.source_documents if doc.publisher == "reuters.com")
    reuters_artifact = result.source_text_artifacts[reuters_doc.source_id]
    assert reuters_artifact.raw_markdown == "raw Reuters markdown"
    assert reuters_artifact.fit_markdown == "fit Reuters markdown"
    assert reuters_artifact.cleaned_text == "Soleimani conflict strike on 2020-01-03 involved US and Iran forces."


def test_news_agent_passes_event_query_to_fetcher():
    registry = SourceRegistry(
        [
            SourceEntry(domain="reuters.com", source_tier="P1", source_type="wire", language="en"),
        ]
    )
    url = "https://www.reuters.com/world/soleimani-jan-3"
    search = StaticSearchProvider(
        [
            SearchResult(
                url=url,
                title="Soleimani conflict strike on 2020-01-03",
                snippet="US Iran conflict latest Strait of Hormuz analysis",
                published_at="2020-01-03",
            ),
        ]
    )

    class RecordingFetcher:
        def __init__(self):
            self.queries: list[str | None] = []

        def fetch(self, url: str, query: str | None = None) -> FetchedPage:
            self.queries.append(query)
            return FetchedPage(
                url=url,
                title="Soleimani conflict strike on 2020-01-03",
                text="Soleimani conflict strike on 2020-01-03 involved US and Iran forces.",
                published_at="2020-01-03",
                status="success",
            )

    scope = Coordinator().confirm_scope(
        "Soleimani conflict",
        confirmed_event="Soleimani conflict",
        confirmed_scope="Soleimani conflict involving US and Iran forces",
    )
    baseline = [
        TimelineItem(
            timeline_item_id="tl_001",
            time_type="point",
            start_date="2020-01-03",
            title="Soleimani conflict strike",
            summary="Soleimani conflict strike on 2020-01-03",
            search_keywords=["Soleimani conflict", "strike"],
        ),
    ]
    task = Coordinator().build_timeline_collection_task(scope, baseline, event_id="event_test")
    fetcher = RecordingFetcher()
    agent = NewsAgent(SourceCollector(registry, search), fetcher=fetcher)

    agent.run(task)

    assert fetcher.queries
    assert "Soleimani conflict involving US and Iran forces" in fetcher.queries[0]
    assert "Soleimani conflict strike" in fetcher.queries[0]
    assert "US Iran conflict latest Strait of Hormuz analysis" in fetcher.queries[0]
