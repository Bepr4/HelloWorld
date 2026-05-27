# 这个测试文件验证 LLM 新闻工具 Agent 会让模型先调用搜索/抓取工具，再产出结构化新闻结果。
from module1.intake.coordinator import Coordinator
from module1.llm.agent_client import FakeAgentClient
from module1.models import FetchedPage, SearchResult, TimelineItem
from module1.news.fetcher import InMemoryFetcher
from module1.news.llm_tool_agent import LLMNewsToolAgent
from module1.news.source_collector import StaticSearchProvider
from module1.news.source_registry import SourceEntry, SourceRegistry


def test_llm_tool_agent_searches_fetches_and_accepts_sources():
    registry = SourceRegistry(
        [
            SourceEntry(domain="aljazeera.com", source_tier="P1", source_type="international_media", language="en"),
        ]
    )
    task = Coordinator().build_timeline_collection_task(
        Coordinator().confirm_scope("最新美伊冲突", confirmed_event="最新美伊冲突"),
        [
            TimelineItem(
                timeline_item_id="tl_001",
                time_type="background",
                title="最新美伊冲突",
                summary="最新美伊冲突",
            )
        ],
        event_id="event_test",
    )
    url = "https://www.aljazeera.com/news/test"
    search_provider = StaticSearchProvider(
        [
            SearchResult(
                url=url,
                title="US Iran tensions rise",
                snippet="US and Iran conflict latest developments",
                discovery_method="rss_feed",
            )
        ]
    )
    fetcher = InMemoryFetcher(
        {
            url: FetchedPage(
                url=url,
                title="US Iran tensions rise",
                text="US and Iran tensions rose after new military warnings.",
                status="success",
            )
        }
    )
    client = FakeAgentClient(
        text_responses=[
            '{"thought":"search English aliases","tool_calls":[{"tool":"web_search","args":{"queries":["site:aljazeera.com US Iran conflict latest"]}}],"final":null}',
            f'{{"thought":"fetch candidate","tool_calls":[{{"tool":"fetch_url","args":{{"url":"{url}"}}}}],"final":null}}',
            f'{{"thought":"done","tool_calls":[],"final":{{"accepted_urls":["{url}"],"news_blocks":[{{"title":"US-Iran tensions","summary":"Sources report renewed US-Iran tensions.","source_urls":["{url}"],"reported_facts":[{{"text":"US and Iran tensions rose.","source_url":"{url}"}}]}}],"timeline_update_suggestions":[]}}}}',
        ]
    )
    agent = LLMNewsToolAgent(source_registry=registry, search_provider=search_provider, fetcher=fetcher)

    result = agent.run(task, agent_client=client)

    assert len(client.calls) == 3
    assert len(result.source_documents) == 1
    assert result.source_documents[0].url == url
    assert len(result.news_blocks) == 1
    assert result.news_blocks[0].source_refs == [result.source_documents[0].source_id]


def test_llm_tool_agent_records_tool_failure_without_crashing():
    registry = SourceRegistry(
        [
            SourceEntry(domain="aljazeera.com", source_tier="P1", source_type="international_media", language="en"),
        ]
    )
    task = Coordinator().build_timeline_collection_task(
        Coordinator().confirm_scope("最新美伊冲突", confirmed_event="最新美伊冲突"),
        [TimelineItem(timeline_item_id="tl_001", time_type="background", title="最新美伊冲突", summary="最新美伊冲突")],
        event_id="event_test",
    )

    class FailingSearchProvider:
        def search(self, queries: list[str]):
            raise TimeoutError("timed out")

    client = FakeAgentClient(
        text_responses=[
            '{"thought":"try web search","tool_calls":[{"tool":"web_search","args":{"queries":["site:aljazeera.com US Iran conflict latest"]}}],"final":null}',
            '{"thought":"stop","tool_calls":[],"final":{"accepted_urls":[],"news_blocks":[],"timeline_update_suggestions":[]}}',
        ]
    )
    events = []
    agent = LLMNewsToolAgent(
        source_registry=registry,
        search_provider=FailingSearchProvider(),
        fetcher=InMemoryFetcher({}),
    )

    result = agent.run(task, agent_client=client, emit=lambda *args: events.append(args))

    assert result.source_documents == []
    assert any(event[0] == "tool_call" and event[1] == "failed" for event in events)


def test_llm_tool_agent_rejects_rss_search_in_web_search_flow():
    registry = SourceRegistry(
        [
            SourceEntry(domain="aljazeera.com", source_tier="P1", source_type="international_media", language="en"),
        ]
    )
    task = Coordinator().build_timeline_collection_task(
        Coordinator().confirm_scope("最新美伊冲突", confirmed_event="最新美伊冲突"),
        [TimelineItem(timeline_item_id="tl_001", time_type="background", title="最新美伊冲突", summary="最新美伊冲突")],
        event_id="event_test",
    )
    client = FakeAgentClient(
        text_responses=[
            '{"thought":"mistaken rss call","tool_calls":[{"tool":"rss_search","args":{"queries":["site:aljazeera.com US Iran conflict latest"]}}],"final":null}',
            '{"thought":"stop","tool_calls":[],"final":{"accepted_urls":[],"news_blocks":[],"timeline_update_suggestions":[]}}',
        ]
    )
    events = []
    agent = LLMNewsToolAgent(
        source_registry=registry,
        search_provider=StaticSearchProvider([]),
        fetcher=InMemoryFetcher({}),
    )

    result = agent.run(task, agent_client=client, emit=lambda *args: events.append(args))

    assert result.source_documents == []
    assert any(
        event[0] == "tool_call"
        and event[1] == "failed"
        and "rss_search is disabled" in event[3]["error"]
        for event in events
    )


def test_llm_tool_agent_uses_partial_documents_when_later_llm_call_times_out():
    registry = SourceRegistry(
        [
            SourceEntry(domain="aljazeera.com", source_tier="P1", source_type="international_media", language="en"),
        ]
    )
    task = Coordinator().build_timeline_collection_task(
        Coordinator().confirm_scope("最新美伊冲突", confirmed_event="最新美伊冲突"),
        [TimelineItem(timeline_item_id="tl_001", time_type="background", title="最新美伊冲突", summary="最新美伊冲突")],
        event_id="event_test",
    )
    url = "https://www.aljazeera.com/news/test"
    search_provider = StaticSearchProvider(
        [
            SearchResult(
                url=url,
                title="US Iran tensions rise",
                snippet="US and Iran conflict latest developments",
                discovery_method="rss_feed",
            )
        ]
    )
    fetcher = InMemoryFetcher(
        {
            url: FetchedPage(
                url=url,
                title="US Iran tensions rise",
                text="US and Iran tensions rose after new military warnings.",
                status="success",
            )
        }
    )

    class TimeoutAfterFetchClient:
        def __init__(self):
            self.calls = 0

        def chat_text(self, messages: list[dict]) -> str:
            self.calls += 1
            if self.calls == 1:
                return '{"thought":"search","tool_calls":[{"tool":"web_search","args":{"queries":["site:aljazeera.com US Iran conflict latest"]}}],"final":null}'
            if self.calls == 2:
                return f'{{"thought":"fetch","tool_calls":[{{"tool":"fetch_url","args":{{"url":"{url}"}}}}],"final":null}}'
            raise TimeoutError("timed out")

    events = []
    agent = LLMNewsToolAgent(source_registry=registry, search_provider=search_provider, fetcher=fetcher)

    result = agent.run(task, agent_client=TimeoutAfterFetchClient(), emit=lambda *args: events.append(args))

    assert len(result.source_documents) == 1
    assert result.source_documents[0].url == url
    assert any(event[0] == "llm_agent" and event[1] == "warning" for event in events)
