# 这个文件实现新闻 Agent 的编排逻辑：按时间线采集、发现补充材料，并输出新闻块和时间线修正建议。
from __future__ import annotations

from datetime import UTC, datetime

from module1.models import (
    CandidateSource,
    FetchedPage,
    NewsAgentResult,
    SourceDocument,
    SourceTextArtifact,
    TimelineCollectionTask,
    TimelineUpdateSuggestion,
)
from module1.news.block_builder import NewsBlockBuilder
from module1.news.deduper import content_hash, dedupe_source_documents, source_id_for_url
from module1.news.fetch_context import build_fetch_query, fetch_with_query
from module1.news.fetcher import InMemoryFetcher
from module1.news.relevance_judge import RelevanceJudge
from module1.news.source_collector import SourceCollector


class NewsAgent:
    """新闻 Agent 主编排器。

    它把 SourceCollector、Fetcher、RelevanceJudge、NewsBlockBuilder 串起来，
    输出事件基础信息库需要的三类新闻产物。
    """

    def __init__(
        self,
        source_collector: SourceCollector,
        fetcher: object | None = None,
        relevance_judge: RelevanceJudge | None = None,
        block_builder: NewsBlockBuilder | None = None,
    ) -> None:
        self.source_collector = source_collector
        self.fetcher = fetcher or InMemoryFetcher({})
        self.relevance_judge = relevance_judge or RelevanceJudge()
        self.block_builder = block_builder or NewsBlockBuilder()

    def run(self, task: TimelineCollectionTask, agent_client: object | None = None) -> NewsAgentResult:
        """执行 Timeline Pass + Discovery Pass。

        第一版不直接改 baseline_timeline；发现漏节点时只输出 timeline_update_suggestions。
        """

        candidates: list[CandidateSource] = []
        for item in task.baseline_timeline:
            candidates.extend(self.source_collector.collect_for_timeline_item(task, item))
        candidates.extend(self.source_collector.collect_for_discovery(task))

        source_documents: list[SourceDocument] = []
        source_texts: dict[str, str] = {}
        source_text_artifacts: dict[str, SourceTextArtifact] = {}
        suggestions: list[TimelineUpdateSuggestion] = []

        for candidate in _dedupe_candidates(candidates):
            item = _find_item(task, candidate.timeline_item_id)
            fetch_query = build_fetch_query(task, candidate, item=item)
            fetched = fetch_with_query(self.fetcher, candidate.url, fetch_query)
            document = _document_from_candidate(task.event_id, candidate, fetched)
            if fetched.status != "success" or not fetched.text:
                continue
            text = fetched.text or candidate.snippet or ""
            decision = self.relevance_judge.judge_source(document, task, text=text, item=item)
            if not decision.is_relevant or decision.confidence < 0.65:
                continue

            if decision.timeline_item_id:
                document.timeline_item_id = decision.timeline_item_id
            document.relevance_score = decision.confidence
            source_documents.append(document)
            if fetched.status == "success" and fetched.text:
                source_texts[document.source_id] = fetched.text
                source_text_artifacts[document.source_id] = _artifact_from_fetched(fetched)

            if decision.needs_timeline_update_suggestion:
                suggestions.append(_suggestion_from_document(task, document, text))

        source_documents = dedupe_source_documents(source_documents)
        source_ids = {document.source_id for document in source_documents}
        source_texts = {key: value for key, value in source_texts.items() if key in source_ids}
        source_text_artifacts = {key: value for key, value in source_text_artifacts.items() if key in source_ids}
        news_blocks = self.block_builder.build_news_blocks(task, source_documents, source_texts)
        suggestions = _dedupe_suggestions(suggestions)

        return NewsAgentResult(
            source_documents=source_documents,
            news_blocks=news_blocks,
            timeline_update_suggestions=suggestions,
            source_texts=source_texts,
            source_text_artifacts=source_text_artifacts,
        )


def _document_from_candidate(event_id: str, candidate: CandidateSource, fetched: FetchedPage) -> SourceDocument:
    """把候选来源和抓取结果合并成 SourceDocument。"""

    text_hash = content_hash(fetched.text) if fetched.text else None
    return SourceDocument(
        source_id=source_id_for_url(candidate.url),
        event_id=event_id,
        timeline_item_id=candidate.timeline_item_id,
        url=candidate.url,
        title=candidate.title or fetched.title,
        publisher=candidate.publisher,
        published_at=fetched.published_at or candidate.published_at,
        fetched_at=datetime.now(UTC).isoformat(),
        language=candidate.language,
        source_tier=candidate.source_tier,
        source_type=candidate.source_type,
        evidence_role=candidate.evidence_role,
        discovery_method=candidate.discovery_method,
        collection_pass=candidate.collection_pass,
        content_hash=text_hash,
        fetch_status=fetched.status,
        fetch_error=fetched.error,
    )


def _artifact_from_fetched(fetched: FetchedPage) -> SourceTextArtifact:
    """把抓取结果拆成可落盘对比的三层正文，旧 text 字段仍视为最终清洗正文。"""

    cleaned_text = fetched.cleaned_text or fetched.text
    return SourceTextArtifact(
        raw_markdown=fetched.raw_markdown,
        fit_markdown=fetched.fit_markdown,
        cleaned_text=cleaned_text,
    )


def _suggestion_from_document(task: TimelineCollectionTask, document: SourceDocument, text: str) -> TimelineUpdateSuggestion:
    """将 Discovery Pass 发现的重要来源转成时间线修正建议。"""

    suggested_date = _date_from_document(document)
    return TimelineUpdateSuggestion(
        suggestion_id=f"tus_{document.source_id.removeprefix('src_')[:8]}",
        event_id=task.event_id,
        suggested_time_type="point",
        suggested_start_date=suggested_date,
        title=document.title or "Potential missing timeline item",
        reason="Discovery Pass found an in-scope important source that did not match the baseline timeline.",
        supporting_sources=[document.source_id],
        suggested_action="add_timeline_item",
    )


def _date_from_document(document: SourceDocument) -> str | None:
    """第一版优先用发布时间前 10 位作为建议日期。"""

    if document.published_at and len(document.published_at) >= 10:
        return document.published_at[:10]
    return None


def _find_item(task: TimelineCollectionTask, timeline_item_id: str | None):
    """根据 timeline_item_id 找基准时间线项。"""

    if not timeline_item_id:
        return None
    for item in task.baseline_timeline:
        if item.timeline_item_id == timeline_item_id:
            return item
    return None


def _dedupe_candidates(candidates: list[CandidateSource]) -> list[CandidateSource]:
    """新闻 Agent 内部二次去重。

    同一个 URL 如果分别来自 timeline_pass 和 discovery_pass，会先保留不同采集来源；
    后续 SourceDocument 阶段再按 URL/hash 进一步去重。
    """

    seen: set[tuple[str, str]] = set()
    output: list[CandidateSource] = []
    for candidate in candidates:
        key = (candidate.url.lower().rstrip("/"), candidate.collection_pass)
        if key in seen:
            continue
        seen.add(key)
        output.append(candidate)
    return output


def _dedupe_suggestions(suggestions: list[TimelineUpdateSuggestion]) -> list[TimelineUpdateSuggestion]:
    """按日期和标题去重，避免同一个补漏节点生成多条建议。"""

    seen: set[tuple[str | None, str]] = set()
    output: list[TimelineUpdateSuggestion] = []
    for suggestion in suggestions:
        key = (suggestion.suggested_start_date, suggestion.title.lower())
        if key in seen:
            continue
        seen.add(key)
        output.append(suggestion)
    return output
