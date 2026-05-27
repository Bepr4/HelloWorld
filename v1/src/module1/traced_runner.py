# 这个文件提供带过程追踪的模块一运行器，把每一步中间状态发给前端事件流。
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from module1.finance.placeholder import run_finance_placeholder
from module1.intake.coordinator import Coordinator
from module1.intake.timeline_builder import TimelineBuilder
from module1.intake.wiki_client import EmptyWikiClient
from module1.llm.agent_client import FakeAgentClient, build_agent_client
from module1.models import (
    CandidateSource,
    EventInfoPackage,
    EventScopeConfirmation,
    NewsAgentResult,
    SourceDocument,
    SourceTextArtifact,
    TimelineCollectionTask,
    TimelineUpdateSuggestion,
)
from module1.news.agent import (
    _artifact_from_fetched,
    _dedupe_candidates,
    _dedupe_suggestions,
    _document_from_candidate,
    _find_item,
    _suggestion_from_document,
)
from module1.news.block_builder import NewsBlockBuilder
from module1.news.deduper import dedupe_source_documents
from module1.news.fetch_context import build_fetch_query, fetch_with_query
from module1.news.llm_tool_agent import LLMNewsToolAgent
from module1.news.relevance_judge import RelevanceJudge
from module1.news.source_collector import SourceCollector
from module1.news.source_registry import SourceRegistry
from module1.pipeline import _build_fetcher, _build_search_provider
from module1.settings import Module1Settings
from module1.storage import StorageWriter


TraceCallback = Callable[[str, str, str, dict[str, Any] | None], None]


def run_module1_traced(
    event_query: str,
    *,
    settings: Module1Settings,
    emit: TraceCallback,
    scope: EventScopeConfirmation | None = None,
    registry_path: str | Path | None = None,
) -> tuple[EventInfoPackage, Path]:
    """运行模块一，并把所有关键中间过程通过 emit 发出去。"""

    emit(
        "config",
        "started",
        "读取运行配置",
        {
            "llm_provider": settings.llm_provider,
            "llm_model": settings.llm_model,
            "llm_wire_api": settings.llm_wire_api,
            "search_provider": settings.search_provider,
            "storage_root": str(settings.storage_root),
        },
    )
    try:
        agent_client = build_agent_client(settings)
        emit("config", "completed", "模型客户端已初始化", {"client": agent_client.__class__.__name__})
    except Exception as exc:
        agent_client = FakeAgentClient()
        emit(
            "config",
            "warning",
            "模型客户端初始化失败，已切到 FakeAgentClient",
            {"error": str(exc), "client": agent_client.__class__.__name__},
        )

    coordinator = Coordinator()
    emit("scope", "started", "确认事件范围", {"event_query": event_query})
    scope = scope or coordinator.confirm_scope(event_query)
    emit("scope", "completed", "事件范围已确认", scope.model_dump(mode="json"))

    emit("timeline", "started", "生成基准事件时间线", {"source": "wiki_client_or_fallback"})
    baseline_timeline = TimelineBuilder(EmptyWikiClient()).build_baseline_timeline(scope, agent_client=agent_client)
    emit(
        "timeline",
        "completed",
        f"基准时间线生成完成，共 {len(baseline_timeline)} 项",
        {"baseline_timeline": [item.model_dump(mode="json") for item in baseline_timeline]},
    )

    emit("task", "started", "生成时间线驱动采集任务单", None)
    task = coordinator.build_timeline_collection_task(scope, baseline_timeline)
    emit("task", "completed", "采集任务单已生成", task.model_dump(mode="json"))

    emit("sources", "started", "加载来源白名单", None)
    source_registry = SourceRegistry.from_yaml(registry_path or Path("configs/module1/source_registry.yaml"))
    tier_counts = {
        tier: len(source_registry.domains_for_tier(tier))
        for tier in ["P0", "P1", "P2", "P3"]
    }
    emit("sources", "completed", "来源白名单已加载", {"tier_counts": tier_counts})

    emit("news_collect", "started", "初始化新闻发现与网页抓取工具", None)
    source_collector = SourceCollector(source_registry, _build_search_provider(settings))
    fetcher = _build_fetcher(settings)
    emit(
        "news_collect",
        "completed",
        "新闻工具已就绪",
        {
            "search_provider": source_collector.search_provider.__class__.__name__,
            "fetcher": fetcher.__class__.__name__,
        },
    )

    if settings.news_agent_mode == "llm_tools":
        emit(
            "news_agent",
            "started",
            "启动 LLM 工具新闻 Agent：由 LLM 决定搜索、RSS 和网页抓取工具调用",
            {
                "mode": settings.news_agent_mode,
                "max_steps": settings.news_agent_max_steps,
                "max_tool_calls": settings.news_agent_max_tool_calls,
            },
        )
        news_result = LLMNewsToolAgent(
            source_registry=source_registry,
            search_provider=source_collector.search_provider,
            fetcher=fetcher,
            max_steps=settings.news_agent_max_steps,
            max_tool_calls=settings.news_agent_max_tool_calls,
        ).run(task, agent_client=agent_client, emit=emit)
        emit("news_agent", "completed", "LLM 工具新闻 Agent 运行完成", news_result.model_dump(mode="json"))
    else:
        candidates = _collect_candidates_with_trace(task, source_collector, emit)
        news_result = _build_news_result_with_trace(task, candidates, fetcher, emit)

    emit("finance", "started", "执行金融 Agent 占位逻辑", None)
    finance_result = run_finance_placeholder(task)
    emit("finance", "completed", "金融占位结果已生成", finance_result)

    emit("storage", "started", "写入事件基础信息库", None)
    storage = StorageWriter(settings.storage_root)
    package = storage.build_event_info_package(
        scope=scope,
        task=task,
        baseline_timeline=baseline_timeline,
        news_result=news_result,
        finance_result=finance_result,
    )
    output_dir = storage.save_event_package(
        package,
        source_texts=news_result.source_texts,
        source_text_artifacts=news_result.source_text_artifacts,
    )
    emit(
        "storage",
        "completed",
        "事件基础信息库已写入磁盘",
        {
            "output_dir": str(output_dir),
            "event_id": package.event_id,
            "source_documents": len(package.source_documents),
            "news_blocks": len(package.news_blocks),
            "timeline_update_suggestions": len(package.timeline_update_suggestions),
        },
    )

    emit("done", "completed", "模块一运行完成", package.model_dump(mode="json"))
    return package, output_dir


def _collect_candidates_with_trace(
    task: TimelineCollectionTask,
    source_collector: SourceCollector,
    emit: TraceCallback,
) -> list[CandidateSource]:
    """执行 Timeline Pass 和 Discovery Pass，并逐步发出候选来源事件。"""

    candidates: list[CandidateSource] = []
    for item in task.baseline_timeline:
        emit(
            "timeline_pass",
            "started",
            f"围绕时间项采集：{item.title}",
            item.model_dump(mode="json"),
        )
        item_candidates = source_collector.collect_for_timeline_item(task, item)
        candidates.extend(item_candidates)
        emit(
            "timeline_pass",
            "completed",
            f"时间项采集完成，发现 {len(item_candidates)} 个候选来源",
            {"timeline_item_id": item.timeline_item_id, "candidates": _candidate_payloads(item_candidates)},
        )

    emit("discovery_pass", "started", "执行 Discovery Pass 补漏搜索", None)
    discovery_candidates = source_collector.collect_for_discovery(task)
    candidates.extend(discovery_candidates)
    emit(
        "discovery_pass",
        "completed",
        f"Discovery Pass 完成，发现 {len(discovery_candidates)} 个候选来源",
        {"candidates": _candidate_payloads(discovery_candidates)},
    )

    deduped = _dedupe_candidates(candidates)
    emit(
        "candidate_dedupe",
        "completed",
        f"候选来源去重完成：{len(candidates)} -> {len(deduped)}",
        {"candidates": _candidate_payloads(deduped)},
    )
    return deduped


def _build_news_result_with_trace(
    task: TimelineCollectionTask,
    candidates: list[CandidateSource],
    fetcher: object,
    emit: TraceCallback,
) -> NewsAgentResult:
    """抓取候选来源、判断相关性，并构造 NewsAgentResult。"""

    relevance_judge = RelevanceJudge()
    block_builder = NewsBlockBuilder()
    source_documents: list[SourceDocument] = []
    source_texts: dict[str, str] = {}
    source_text_artifacts: dict[str, SourceTextArtifact] = {}
    suggestions: list[TimelineUpdateSuggestion] = []

    for index, candidate in enumerate(candidates, start=1):
        emit(
            "fetch",
            "started",
            f"抓取来源 {index}/{len(candidates)}",
            candidate.model_dump(mode="json"),
        )
        item = _find_item(task, candidate.timeline_item_id)
        fetch_query = build_fetch_query(task, candidate, item=item)
        fetched = fetch_with_query(fetcher, candidate.url, fetch_query)
        document = _document_from_candidate(task.event_id, candidate, fetched)
        emit(
            "fetch",
            fetched.status,
            fetched.title or candidate.title or candidate.url,
            {
                "url": candidate.url,
                "status": fetched.status,
                "title": fetched.title or candidate.title,
                "text_length": len(fetched.text or ""),
                "raw_markdown_length": len(fetched.raw_markdown or ""),
                "fit_markdown_length": len(fetched.fit_markdown or ""),
                "cleaned_text_length": len(fetched.cleaned_text or fetched.text or ""),
                "error": fetched.error,
            },
        )

        text = fetched.text or candidate.snippet or ""
        decision = relevance_judge.judge_source(document, task, text=text, item=item)
        emit(
            "relevance",
            "completed" if decision.is_relevant else "rejected",
            decision.reason,
            {
                "url": candidate.url,
                "title": document.title,
                "decision": decision.model_dump(mode="json"),
            },
        )
        if not decision.is_relevant or decision.confidence < 0.65:
            continue

        if decision.timeline_item_id:
            document.timeline_item_id = decision.timeline_item_id
        document.relevance_score = decision.confidence
        source_documents.append(document)
        if fetched.status == "success" and fetched.text:
            source_texts[document.source_id] = fetched.text
            source_text_artifacts[document.source_id] = _artifact_from_fetched(fetched)
        emit("accepted_source", "completed", document.title or document.url, document.model_dump(mode="json"))

        if decision.needs_timeline_update_suggestion:
            suggestion = _suggestion_from_document(task, document, text)
            suggestions.append(suggestion)
            emit("timeline_suggestion", "completed", suggestion.title, suggestion.model_dump(mode="json"))

    source_documents = dedupe_source_documents(source_documents)
    source_ids = {document.source_id for document in source_documents}
    source_texts = {key: value for key, value in source_texts.items() if key in source_ids}
    source_text_artifacts = {key: value for key, value in source_text_artifacts.items() if key in source_ids}
    emit(
        "source_dedupe",
        "completed",
        f"可用来源去重完成，共 {len(source_documents)} 条",
        {"source_documents": [document.model_dump(mode="json") for document in source_documents]},
    )

    news_blocks = block_builder.build_news_blocks(task, source_documents, source_texts)
    suggestions = _dedupe_suggestions(suggestions)
    emit(
        "news_blocks",
        "completed",
        f"新闻事件块生成完成，共 {len(news_blocks)} 块",
        {"news_blocks": [block.model_dump(mode="json") for block in news_blocks]},
    )

    return NewsAgentResult(
        source_documents=source_documents,
        news_blocks=news_blocks,
        timeline_update_suggestions=suggestions,
        source_texts=source_texts,
        source_text_artifacts=source_text_artifacts,
    )


def _candidate_payloads(candidates: list[CandidateSource]) -> list[dict[str, Any]]:
    """把候选来源转成前端可直接展示的 JSON。"""

    return [candidate.model_dump(mode="json") for candidate in candidates]
