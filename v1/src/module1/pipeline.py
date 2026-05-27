# 这个文件串联模块一 v1 的端到端流程，从用户事件输入生成事件基础信息库 JSON。
from __future__ import annotations

from pathlib import Path

from module1.finance.placeholder import run_finance_placeholder
from module1.intake.coordinator import Coordinator
from module1.intake.timeline_builder import TimelineBuilder
from module1.intake.wiki_client import EmptyWikiClient
from module1.llm.agent_client import AgentClient, build_agent_client
from module1.models import EventInfoPackage, EventScopeConfirmation
from module1.news.agent import NewsAgent
from module1.news.fetcher import Crawl4AIFetcher, InMemoryFetcher
from module1.news.llm_tool_agent import LLMNewsToolAgent
from module1.news.search_providers import (
    BraveSearchProvider,
    CompositeSearchProvider,
    RssSearchProvider,
    TavilySearchProvider,
    WebSearchProvider,
)
from module1.news.source_collector import StaticSearchProvider, SourceCollector
from module1.news.source_registry import SourceRegistry
from module1.settings import Module1Settings, load_module1_settings
from module1.storage import StorageWriter


def run_module1(
    event_query: str,
    *,
    scope: EventScopeConfirmation | None = None,
    settings: Module1Settings | None = None,
    agent_client: AgentClient | None = None,
    wiki_client: object | None = None,
    search_provider: object | None = None,
    fetcher: object | None = None,
    source_registry: SourceRegistry | None = None,
    registry_path: str | Path | None = None,
) -> EventInfoPackage:
    """模块一第一版端到端入口。

    当前 pipeline 的终点是保存 EventInfoPackage，不生成事件地图 Agent 或 Context Map。
    依赖项都允许注入，方便用 mock/fake 数据测试，不强制联网。
    """

    settings = settings or load_module1_settings(require_llm_key=False)
    agent_client = agent_client or build_agent_client(settings)

    # 1. 先确认事件范围；没有明确 scope 时，第一版先用 query 生成半自动确认对象。
    coordinator = Coordinator()
    scope = scope or coordinator.confirm_scope(event_query)

    # 2. 生成基准时间线。没有 Wiki 数据时会退化成 background 节点。
    baseline_timeline = TimelineBuilder(wiki_client or EmptyWikiClient()).build_baseline_timeline(
        scope,
        agent_client=agent_client,
    )
    task = coordinator.build_timeline_collection_task(scope, baseline_timeline)

    # 3. 加载来源注册表；未知来源后续会被 SourceCollector 丢弃。
    if source_registry is None:
        registry_path = registry_path or Path("configs/module1/source_registry.yaml")
        source_registry = SourceRegistry.from_yaml(registry_path)

    # 4. 跑新闻 Agent。真实环境会按 settings.search_provider 选择 RSS/Brave 搜索和 urllib 抓取器。
    collector = SourceCollector(
        source_registry=source_registry,
        search_provider=search_provider or _build_search_provider(settings),
    )
    resolved_fetcher = fetcher or _build_fetcher(settings)
    if settings.news_agent_mode == "llm_tools":
        news_result = LLMNewsToolAgent(
            source_registry=source_registry,
            search_provider=collector.search_provider,
            fetcher=resolved_fetcher,
            max_steps=settings.news_agent_max_steps,
            max_tool_calls=settings.news_agent_max_tool_calls,
        ).run(task, agent_client=agent_client)
    else:
        news_agent = NewsAgent(
            source_collector=collector,
            fetcher=resolved_fetcher,
        )
        news_result = news_agent.run(task, agent_client=agent_client)
    finance_result = run_finance_placeholder(task)

    # 5. 金融第一版只是占位，最终把新闻结果和金融占位一起写成事件基础信息库。
    storage = StorageWriter(settings.storage_root)
    package = storage.build_event_info_package(
        scope=scope,
        task=task,
        baseline_timeline=baseline_timeline,
        news_result=news_result,
        finance_result=finance_result,
    )
    storage.save_event_package(
        package,
        source_texts=news_result.source_texts,
        source_text_artifacts=news_result.source_text_artifacts,
    )
    return package


def _build_search_provider(settings: Module1Settings):
    """按配置创建真实或空搜索服务。"""

    provider = settings.search_provider.lower()
    if provider in {"none", "manual", "static", "fake", "mock"}:
        return StaticSearchProvider([])
    if provider == "rss":
        return RssSearchProvider.from_yaml(
            settings.news_feeds_path,
            user_agent=settings.user_agent,
            timeout=settings.http_timeout_seconds,
        )
    if provider in {"web", "web_search", "tavily"}:
        return TavilySearchProvider(
            settings.search_api_key.get_secret_value() if settings.search_api_key else "",
            endpoint=settings.tavily_search_endpoint,
            timeout=settings.http_timeout_seconds,
            count=settings.search_results_per_query,
        )
    if provider == "brave":
        return WebSearchProvider(
            settings.search_api_key.get_secret_value() if settings.search_api_key else "",
            endpoint=settings.brave_search_endpoint,
            timeout=settings.http_timeout_seconds,
            count=settings.search_results_per_query,
        )
    if provider in {"rss_brave", "brave_rss", "hybrid"}:
        return CompositeSearchProvider(
            [
                RssSearchProvider.from_yaml(
                    settings.news_feeds_path,
                    user_agent=settings.user_agent,
                    timeout=settings.http_timeout_seconds,
                ),
                BraveSearchProvider(
                    settings.search_api_key.get_secret_value() if settings.search_api_key else "",
                    endpoint=settings.brave_search_endpoint,
                    timeout=settings.http_timeout_seconds,
                    count=settings.search_results_per_query,
                ),
            ]
        )
    raise ValueError(f"Unsupported MODULE1_SEARCH_PROVIDER: {settings.search_provider}")


def _build_fetcher(settings: Module1Settings):
    """真实搜索时统一用 Crawl4AI 抓网页；空搜索时保留内存抓取器方便测试。"""

    provider = settings.search_provider.lower()
    if provider in {"none", "manual", "static", "fake", "mock"}:
        return InMemoryFetcher({})
    return Crawl4AIFetcher(
        user_agent=settings.user_agent,
        timeout=settings.http_timeout_seconds,
        enable_stealth=settings.crawl4ai_enable_stealth,
        use_undetected_on_block=settings.crawl4ai_use_undetected,
        headless=settings.crawl4ai_headless,
        max_retries=settings.crawl4ai_max_retries,
        managed_profile_dir=settings.crawl4ai_profile_dir,
        proxy=settings.crawl4ai_proxy,
        enable_bm25_filter=settings.crawl4ai_enable_bm25,
        bm25_threshold=settings.crawl4ai_bm25_threshold,
        bm25_language=settings.crawl4ai_bm25_language,
    )
