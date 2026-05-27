# 这个文件实现真正的新闻工具 Agent：LLM 决定调用 RSS/搜索/抓取工具，Python 负责安全执行和落盘结构化。
from __future__ import annotations

# 这个文件实现模块一的 LLM 新闻工具 Agent，负责编排搜索、抓取和最终新闻来源筛选。
import json
import re
from collections import defaultdict
from typing import Any

from module1.models import (
    CandidateSource,
    NewsAgentResult,
    NewsBlock,
    SourceDocument,
    SourceTextArtifact,
    TimelineCollectionTask,
    TimelineUpdateSuggestion,
)
from module1.news.agent import _artifact_from_fetched, _document_from_candidate
from module1.news.block_builder import NewsBlockBuilder
from module1.news.deduper import dedupe_source_documents
from module1.news.fetch_context import build_fetch_query, fetch_with_query
from module1.news.source_registry import SourceEntry, SourceRegistry
from module1.news.text_cleaner import first_meaningful_excerpt


class LLMNewsToolAgent:
    """让 LLM 通过工具循环主动搜索和抓取新闻。"""

    def __init__(
        self,
        *,
        source_registry: SourceRegistry,
        search_provider: object,
        fetcher: object,
        max_steps: int = 6,
        max_tool_calls: int = 5,
    ) -> None:
        self.source_registry = source_registry
        self.search_provider = search_provider
        self.fetcher = fetcher
        self.max_steps = max_steps
        self.max_tool_calls = max_tool_calls
        self.candidates_by_url: dict[str, CandidateSource] = {}
        self.documents_by_url: dict[str, SourceDocument] = {}
        self.source_texts: dict[str, str] = {}
        self.source_text_artifacts: dict[str, SourceTextArtifact] = {}

    def run(self, task: TimelineCollectionTask, *, agent_client: object, emit=None) -> NewsAgentResult:
        """执行 LLM 工具循环，并返回新闻 Agent 结构化结果。"""

        emit = emit or (lambda *_args, **_kwargs: None)
        messages = [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": _task_prompt(task, self.source_registry)},
        ]
        final_payload: dict[str, Any] | None = None

        for step in range(1, self.max_steps + 1):
            emit("llm_agent", "started", f"LLM 决策第 {step} 轮", {"messages": len(messages)})
            try:
                raw = agent_client.chat_text(messages)
            except Exception as exc:
                emit(
                    "llm_agent",
                    "warning" if self.documents_by_url else "failed",
                    f"LLM 决策第 {step} 轮调用失败，使用已抓取材料继续" if self.documents_by_url else f"LLM 决策第 {step} 轮调用失败",
                    {
                        "error": f"{exc.__class__.__name__}: {exc}",
                        "partial_documents": len(self.documents_by_url),
                    },
                )
                if self.documents_by_url:
                    final_payload = {}
                    break
                raise

            try:
                decision = _parse_json_object(raw)
            except Exception as exc:
                decision = _repair_decision_json(
                    raw=raw,
                    parse_error=exc,
                    messages=messages,
                    agent_client=agent_client,
                    emit=emit,
                    step=step,
                )
                if decision is None:
                    emit(
                        "llm_agent",
                        "warning" if self.documents_by_url else "failed",
                        f"LLM 决策第 {step} 轮 JSON 修复失败，使用已抓取材料继续" if self.documents_by_url else f"LLM 决策第 {step} 轮 JSON 修复失败",
                        {
                            "error": f"{exc.__class__.__name__}: {exc}",
                            "partial_documents": len(self.documents_by_url),
                        },
                    )
                    if self.documents_by_url:
                        final_payload = None
                        break
                    raise
            emit(
                "llm_agent",
                "completed",
                decision.get("thought") or "LLM returned a tool decision",
                {"decision": decision},
            )

            final_payload = decision.get("final")
            if isinstance(final_payload, dict):
                emit("llm_agent_final", "completed", "LLM 已给出最终采集决策", final_payload)
                break

            tool_calls = decision.get("tool_calls") or []
            if not isinstance(tool_calls, list):
                tool_calls = []
            observations = []
            for call in tool_calls[: self.max_tool_calls]:
                observation = self._execute_tool(call, task, emit)
                observations.append(observation)
            messages.append({"role": "assistant", "content": json.dumps(decision, ensure_ascii=False)})
            messages.append(
                {
                    "role": "user",
                    "content": "Tool observations:\n" + json.dumps(observations, ensure_ascii=False, indent=2),
                }
            )

        if not isinstance(final_payload, dict) and self.documents_by_url:
            final_payload = _force_final_decision(
                messages=messages,
                agent_client=agent_client,
                emit=emit,
                documents=list(self.documents_by_url.values()),
            )

        return self._build_result(task, final_payload or {}, emit, agent_client=agent_client)

    def _execute_tool(self, call: dict, task: TimelineCollectionTask, emit) -> dict:
        tool = str(call.get("tool", ""))
        args = call.get("args") if isinstance(call.get("args"), dict) else {}
        emit("tool_call", "started", f"LLM 调用工具：{tool}", {"tool": tool, "args": args})
        try:
            if tool == "list_sources":
                observation = self._tool_list_sources()
            elif tool in {"web_search", "search_news"}:
                observation = self._tool_search(args, tool)
            elif tool == "rss_search":
                observation = {
                    "ok": False,
                    "error": "rss_search is disabled in the current v1 flow. Use web_search instead.",
                }
            elif tool == "fetch_url":
                observation = self._tool_fetch_url(args, task)
            elif tool == "finish":
                observation = {"ok": True, "message": "Use final in the next response."}
            else:
                observation = {"ok": False, "error": f"unknown tool: {tool}"}
        except Exception as exc:
            observation = {
                "ok": False,
                "tool": tool,
                "error": f"{exc.__class__.__name__}: {exc}",
            }
        emit("tool_call", "completed" if observation.get("ok") else "failed", f"工具返回：{tool}", observation)
        return {"tool": tool, "observation": observation}

    def _tool_list_sources(self) -> dict:
        return {
            "ok": True,
            "sources": [
                {
                    "domain": source.domain,
                    "tier": source.source_tier,
                    "type": source.source_type,
                    "region": source.region,
                    "language": source.language,
                }
                for source in self.source_registry.sources
            ],
        }

    def _tool_search(self, args: dict, tool: str) -> dict:
        queries = args.get("queries") or []
        if isinstance(args.get("query"), str):
            queries.append(args["query"])
        queries = [str(query) for query in queries if str(query).strip()]
        if not queries:
            return {"ok": False, "error": "queries is required"}

        results = self.search_provider.search(queries)
        candidates = []
        for result in results:
            source_meta = self.source_registry.match(result.url)
            if not source_meta:
                continue
            candidate = _candidate_from_result(result, source_meta, tool)
            self.candidates_by_url[_url_key(candidate.url)] = candidate
            candidates.append(candidate.model_dump(mode="json"))

        return {
            "ok": True,
            "tool": tool,
            "provider": self.search_provider.__class__.__name__,
            "queries": queries,
            "count": len(candidates),
            "candidates": candidates[:20],
        }

    def _tool_fetch_url(self, args: dict, task: TimelineCollectionTask) -> dict:
        url = str(args.get("url") or "").strip()
        if not url:
            return {"ok": False, "error": "url is required"}

        source_meta = self.source_registry.match(url)
        if not source_meta:
            return {"ok": False, "error": "url rejected by source registry", "url": url}

        key = _url_key(url)
        candidate = self.candidates_by_url.get(key) or _candidate_from_url(url, source_meta)
        fetch_query = build_fetch_query(task, candidate)
        fetched = fetch_with_query(self.fetcher, url, fetch_query)
        document = _document_from_candidate(task.event_id, candidate, fetched)
        if not document.timeline_item_id:
            document.timeline_item_id = _default_timeline_item_id(task)
        self.documents_by_url[key] = document
        if fetched.status == "success" and fetched.text:
            self.source_texts[document.source_id] = fetched.text
            self.source_text_artifacts[document.source_id] = _artifact_from_fetched(fetched)

        return {
            "ok": True,
            "url": url,
            "source_id": document.source_id,
            "title": document.title,
            "publisher": document.publisher,
            "source_tier": document.source_tier,
            "fetch_status": document.fetch_status,
            "fetch_query": fetch_query,
            "published_at": document.published_at,
            "raw_markdown_length": len(fetched.raw_markdown or ""),
            "fit_markdown_length": len(fetched.fit_markdown or ""),
            "cleaned_text_length": len(fetched.cleaned_text or fetched.text or ""),
            "text_preview": (fetched.text or candidate.snippet or "")[:1600],
            "error": fetched.error,
        }

    def _build_result(
        self,
        task: TimelineCollectionTask,
        final_payload: dict[str, Any],
        emit,
        *,
        agent_client: object,
    ) -> NewsAgentResult:
        accepted_urls = [str(url) for url in final_payload.get("accepted_urls", []) if str(url).strip()]
        if not accepted_urls:
            accepted_urls = [document.url for document in self.documents_by_url.values() if document.fetch_status == "success"]

        documents: list[SourceDocument] = []
        for url in accepted_urls:
            document = self.documents_by_url.get(_url_key(url))
            if not document:
                continue
            if document.fetch_status != "success":
                continue
            if not document.timeline_item_id:
                document.timeline_item_id = _default_timeline_item_id(task)
            document.relevance_score = 0.9
            documents.append(document)

        documents = dedupe_source_documents(documents)
        source_ids = {document.source_id for document in documents}
        source_texts = {key: value for key, value in self.source_texts.items() if key in source_ids}
        source_text_artifacts = {key: value for key, value in self.source_text_artifacts.items() if key in source_ids}
        news_blocks = _blocks_from_llm_content(
            task,
            documents,
            source_texts,
            agent_client=agent_client,
            emit=emit,
        )
        if not news_blocks:
            news_blocks = NewsBlockBuilder().build_news_blocks(task, documents, source_texts)
        suggestions = _timeline_suggestions_from_final(task, final_payload, documents)

        if not documents:
            emit(
                "news_agent_empty",
                "warning",
                "新闻 Agent 没有采集到可接受来源",
                {
                    "candidate_count": len(self.candidates_by_url),
                    "fetched_count": len(self.documents_by_url),
                    "likely_reason": _empty_result_reason(
                        candidate_count=len(self.candidates_by_url),
                        documents=list(self.documents_by_url.values()),
                    ),
                },
            )

        emit(
            "llm_agent_result",
            "completed",
            f"LLM 工具 Agent 产出 {len(documents)} 条来源、{len(news_blocks)} 个新闻块",
            {
                "accepted_urls": accepted_urls,
                "source_documents": [document.model_dump(mode="json") for document in documents],
                "news_blocks": [block.model_dump(mode="json") for block in news_blocks],
            },
        )
        return NewsAgentResult(
            source_documents=documents,
            news_blocks=news_blocks,
            timeline_update_suggestions=suggestions,
            source_texts=source_texts,
            source_text_artifacts=source_text_artifacts,
        )


def _repair_decision_json(
    *,
    raw: str,
    parse_error: Exception,
    messages: list[dict[str, str]],
    agent_client: object,
    emit,
    step: int,
) -> dict[str, Any] | None:
    """当模型输出损坏 JSON 时，请模型只修复 JSON，一次失败后再走兜底逻辑。"""

    emit(
        "llm_agent_repair",
        "started",
        f"LLM 决策第 {step} 轮 JSON 解析失败，尝试自动修复",
        {
            "error": f"{parse_error.__class__.__name__}: {parse_error}",
            "raw_preview": raw[:1200],
        },
    )
    repair_messages = [
        *messages,
        {
            "role": "assistant",
            "content": raw,
        },
        {
            "role": "user",
            "content": (
                "The previous assistant message was intended to be JSON but is invalid. "
                "Return ONLY one repaired JSON object using the same schema. "
                "Do not add markdown or explanations."
            ),
        },
    ]
    try:
        repaired_raw = agent_client.chat_text(repair_messages)
        decision = _parse_json_object(repaired_raw)
    except Exception as exc:
        emit(
            "llm_agent_repair",
            "failed",
            "LLM JSON 自动修复失败",
            {
                "error": f"{exc.__class__.__name__}: {exc}",
                "raw_preview": raw[:1200],
            },
        )
        return None

    emit(
        "llm_agent_repair",
        "completed",
        "LLM JSON 自动修复成功",
        {"decision": decision},
    )
    return decision


def _force_final_decision(
    *,
    messages: list[dict[str, str]],
    agent_client: object,
    emit,
    documents: list[SourceDocument],
) -> dict[str, Any]:
    """工具轮数用尽时再要求模型做一次最终选择，避免静默接受所有成功抓取页面。"""

    compact_documents = [
        {
            "url": document.url,
            "title": document.title,
            "publisher": document.publisher,
            "fetch_status": document.fetch_status,
            "fetch_error": document.fetch_error,
        }
        for document in documents
    ]
    emit(
        "llm_agent_force_final",
        "started",
        "LLM 工具轮数已用尽，要求模型只返回轻量最终选择",
        {"documents": compact_documents},
    )
    final_messages = [
        *messages,
        {
            "role": "user",
            "content": (
                "Tool budget is exhausted. Do not call tools. Return ONLY valid JSON with this schema: "
                '{"thought":"final selection","tool_calls":[],"final":{"accepted_urls":[],"news_blocks":[],"timeline_update_suggestions":[]}}. '
                "Only include URLs whose fetch_status is success. Exclude blocked, failed, metadata_only, topic pages, and low-quality pages. "
                "Keep news_blocks and timeline_update_suggestions as empty arrays; Python will assemble structured blocks later. "
                "Fetched document inventory:\n"
                + json.dumps(compact_documents, ensure_ascii=False, indent=2)
            ),
        },
    ]
    try:
        raw = agent_client.chat_text(final_messages)
        decision = _parse_json_object(raw)
    except Exception as exc:
        repaired = _repair_decision_json(
            raw=raw if "raw" in locals() else "",
            parse_error=exc,
            messages=final_messages,
            agent_client=agent_client,
            emit=emit,
            step=0,
        )
        if repaired is None:
            emit(
                "llm_agent_force_final",
                "failed",
                "LLM 最终选择失败，使用质量门槛后的成功来源兜底",
                {"error": f"{exc.__class__.__name__}: {exc}"},
            )
            return {}
        decision = repaired

    final_payload = decision.get("final") if isinstance(decision, dict) else None
    if isinstance(final_payload, dict):
        emit("llm_agent_force_final", "completed", "LLM 已返回最终选择", final_payload)
        return final_payload

    emit(
        "llm_agent_force_final",
        "failed",
        "LLM 最终选择没有包含 final 字段，使用质量门槛后的成功来源兜底",
        {"decision": decision},
    )
    return {}


def _blocks_from_llm_content(
    task: TimelineCollectionTask,
    documents: list[SourceDocument],
    source_texts: dict[str, str],
    *,
    agent_client: object,
    emit,
) -> list[NewsBlock]:
    """让 LLM 只负责短文案，引用关系、source_refs 和层级统计都由程序生成。"""

    grouped: dict[str, list[SourceDocument]] = defaultdict(list)
    for document in documents:
        if document.fetch_status != "success":
            continue
        timeline_item_id = document.timeline_item_id or _default_timeline_item_id(task)
        grouped[timeline_item_id].append(document)

    blocks: list[NewsBlock] = []
    for index, (timeline_item_id, docs) in enumerate(sorted(grouped.items()), start=1):
        compact_sources = _compact_sources_for_block(docs, source_texts)
        if not compact_sources:
            continue

        emit(
            "llm_agent_block_content",
            "started",
            "让 LLM 只生成新闻块短文案，程序负责最终 JSON 结构",
            {"timeline_item_id": timeline_item_id, "source_count": len(compact_sources)},
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "You write concise news block text from provided fetched sources. "
                    "Return ONLY one compact valid JSON object. Do not use markdown. "
                    "Do not output URLs. Use only source_id values from the input."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Generate concise content for one news block. Python will assemble the final object, "
                    "so you must not select URLs or build the full final JSON. "
                    "Return this schema only: "
                    '{"title":"","summary":"","reported_facts":[{"source_id":"","text":""}],'
                    '"source_summaries":[{"source_id":"","summary":""}],'
                    '"source_differences":[{"topic":"","description":""}]}. '
                    "Keep summary under 180 words, facts under 8 items, and source summaries under 1 sentence each.\n"
                    "Input:\n"
                    + json.dumps(
                        {
                            "event_query": task.event_query,
                            "confirmed_event": task.confirmed_event,
                            "timeline_item_id": timeline_item_id,
                            "baseline_title": _timeline_title_for(task, timeline_item_id),
                            "sources": compact_sources,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                ),
            },
        ]
        try:
            raw = agent_client.chat_text(messages)
            content_payload = _parse_json_object(raw)
        except Exception as exc:
            emit(
                "llm_agent_block_content",
                "warning",
                "LLM 短文案 JSON 生成失败，回退到程序摘要",
                {"error": f"{exc.__class__.__name__}: {exc}", "timeline_item_id": timeline_item_id},
            )
            continue

        block = _block_from_content_payload(
            task=task,
            timeline_item_id=timeline_item_id,
            index=index,
            documents=docs,
            source_texts=source_texts,
            payload=content_payload,
        )
        if block:
            blocks.append(block)
            emit(
                "llm_agent_block_content",
                "completed",
                "LLM 短文案已通过程序校验并组装成 NewsBlock",
                {"timeline_item_id": timeline_item_id, "news_block_id": block.news_block_id},
            )

    return blocks


def _compact_sources_for_block(
    documents: list[SourceDocument],
    source_texts: dict[str, str],
) -> list[dict[str, str | None]]:
    """把长正文压成 source_id + 摘要片段，避免把整篇网页再交给 LLM 生成长 JSON。"""

    compact_sources: list[dict[str, str | None]] = []
    for document in documents[:12]:
        excerpt = first_meaningful_excerpt(source_texts.get(document.source_id, ""), limit=900)
        compact_sources.append(
            {
                "source_id": document.source_id,
                "title": document.title,
                "publisher": document.publisher,
                "published_at": document.published_at,
                "excerpt": excerpt or document.title or "",
            }
        )
    return compact_sources


def _block_from_content_payload(
    *,
    task: TimelineCollectionTask,
    timeline_item_id: str,
    index: int,
    documents: list[SourceDocument],
    source_texts: dict[str, str],
    payload: dict[str, Any],
) -> NewsBlock | None:
    """校验 LLM 的短文案输出，并由程序补齐稳定的结构字段。"""

    source_refs = [document.source_id for document in documents]
    source_ids = set(source_refs)
    title = _short_text(payload.get("title"), limit=180) or documents[0].title or "News update"
    summary = _short_text(payload.get("summary"), limit=1400)
    source_summaries = _source_bound_items(
        payload.get("source_summaries"),
        source_ids=source_ids,
        text_key="summary",
        limit=700,
    )
    reported_facts = _source_bound_items(
        payload.get("reported_facts"),
        source_ids=source_ids,
        text_key="text",
        limit=700,
    )

    # 如果短文案缺字段，程序用已清洗正文兜底，仍然不让 LLM 生成完整 final JSON。
    if not source_summaries:
        source_summaries = _fallback_source_items(documents, source_texts, text_key="summary")
    if not reported_facts:
        reported_facts = _fallback_source_items(documents, source_texts, text_key="text")
    if not summary:
        summary = _summary_from_items(source_summaries) or _timeline_title_for(task, timeline_item_id)

    if not source_refs:
        return None

    return NewsBlock(
        news_block_id=f"nb_{index:03d}",
        event_id=task.event_id,
        timeline_item_id=timeline_item_id,
        title=title,
        summary=summary,
        event_time=_event_time_for(task, timeline_item_id),
        reported_facts=reported_facts,
        source_summaries=source_summaries,
        source_differences=_source_differences(payload.get("source_differences")),
        source_refs=source_refs,
        source_tier_summary=_tier_summary(documents, source_refs),
    )


def _source_bound_items(
    items: Any,
    *,
    source_ids: set[str],
    text_key: str,
    limit: int,
) -> list[dict[str, str]]:
    """只保留能映射到已接受 source_id 的 LLM 文案，防止幻觉来源进入结果。"""

    if not isinstance(items, list):
        return []

    validated: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        source_id = _short_text(item.get("source_id"), limit=80)
        text = _short_text(item.get(text_key) or item.get("text") or item.get("summary"), limit=limit)
        if source_id not in source_ids or not text:
            continue
        validated.append({"source_id": source_id, text_key: text})
    return validated


def _fallback_source_items(
    documents: list[SourceDocument],
    source_texts: dict[str, str],
    *,
    text_key: str,
) -> list[dict[str, str]]:
    """当短文案缺字段时，从清洗正文中抽取可读片段补齐每个来源的说明。"""

    items: list[dict[str, str]] = []
    for document in documents:
        text = first_meaningful_excerpt(source_texts.get(document.source_id, ""), limit=520) or document.title or ""
        if text:
            items.append({"source_id": document.source_id, text_key: text})
    return items


def _source_differences(items: Any) -> list[dict[str, str]]:
    """把 LLM 给出的来源差异压成短字段，不接受任意长文本。"""

    if not isinstance(items, list):
        return []

    differences: list[dict[str, str]] = []
    for item in items:
        if isinstance(item, str):
            description = _short_text(item, limit=700)
            if description:
                differences.append({"description": description})
            continue
        if not isinstance(item, dict):
            continue
        topic = _short_text(item.get("topic"), limit=140)
        description = _short_text(
            item.get("description") or item.get("text") or item.get("difference") or item.get("summary"),
            limit=700,
        )
        if not description:
            continue
        difference = {"description": description}
        if topic:
            difference["topic"] = topic
        differences.append(difference)
    return differences


def _summary_from_items(items: list[dict[str, str]]) -> str:
    """用程序兜底摘要时只拼接短句，避免再混入大段导航噪声。"""

    return " ".join(item.get("summary") or item.get("text") or "" for item in items if item)[:900].strip()


def _short_text(value: Any, *, limit: int) -> str:
    """统一压缩 LLM 文案字段，保持最终 JSON 可读且长度可控。"""

    if not isinstance(value, str):
        return ""
    text = re.sub(r"\s+", " ", value).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _timeline_title_for(task: TimelineCollectionTask, timeline_item_id: str) -> str:
    """根据 timeline_item_id 找到基准时间线标题，用于摘要兜底。"""

    for item in task.baseline_timeline:
        if item.timeline_item_id == timeline_item_id:
            return item.title
    return task.confirmed_event or task.event_query


def _event_time_for(task: TimelineCollectionTask, timeline_item_id: str) -> str | None:
    """根据 timeline_item_id 找到基准时间线日期，用于 NewsBlock.event_time。"""

    for item in task.baseline_timeline:
        if item.timeline_item_id == timeline_item_id:
            return item.start_date
    return None


def _empty_result_reason(*, candidate_count: int, documents: list[SourceDocument]) -> str:
    """根据搜索候选和抓取结果生成更准确的空结果诊断。"""

    fetched_count = len(documents)
    if candidate_count == 0:
        return "web_search 没有返回可进入白名单的候选来源；请检查搜索 API key、搜索 provider 配置或查询词。"
    if fetched_count == 0:
        return "web_search 已返回白名单候选，但 LLM 没有调用 fetch_url 抓取正文；请检查工具调用轮次或模型决策。"

    failed_documents = [document for document in documents if document.fetch_status == "failed"]
    if len(failed_documents) == fetched_count:
        first_error = next((document.fetch_error for document in failed_documents if document.fetch_error), "未知抓取错误")
        return (
            f"web_search 已返回 {candidate_count} 个白名单候选，fetch_url 抓取了 {fetched_count} 个 URL，"
            f"但全部失败；首个错误：{first_error}。请检查 Crawl4AI、浏览器运行权限、网络访问或站点反爬。"
        )

    blocked_documents = [document for document in documents if document.fetch_status == "blocked"]
    if len(blocked_documents) == fetched_count:
        first_error = next((document.fetch_error for document in blocked_documents if document.fetch_error), "站点反爬阻断")
        return (
            f"web_search 已返回 {candidate_count} 个白名单候选，fetch_url 抓取了 {fetched_count} 个 URL，"
            f"但全部被反爬阻断；首个错误：{first_error}。可以配置 Crawl4AI managed profile、undetected browser 或代理。"
        )

    metadata_only_count = sum(1 for document in documents if document.fetch_status == "metadata_only")
    if metadata_only_count == fetched_count:
        return (
            f"web_search 已返回 {candidate_count} 个白名单候选，fetch_url 抓取了 {fetched_count} 个 URL，"
            "但都只有元数据没有可用正文；请检查正文抽取质量或页面动态渲染。"
        )

    return (
        f"web_search 已返回 {candidate_count} 个白名单候选，fetch_url 抓取了 {fetched_count} 个 URL，"
        "但没有最终进入 accepted_urls 的 success 文档；请检查 LLM final.accepted_urls 或抓取状态筛选。"
    )


def _system_prompt() -> str:
    return """
You are Module 1 News Agent. You must actively use web_search and fetch_url tools to discover and fetch news pages.
Return ONLY valid JSON. Do not use markdown.

Each response must be one of:
{
  "thought": "brief reasoning",
  "tool_calls": [
    {"tool": "list_sources", "args": {}},
    {"tool": "web_search", "args": {"queries": ["site:reuters.com US Iran conflict"]}},
    {"tool": "fetch_url", "args": {"url": "https://..."}}
  ],
  "final": null
}

or, when enough pages have been fetched:
{
  "thought": "brief conclusion",
  "tool_calls": [],
  "final": {
    "accepted_urls": ["https://..."],
    "news_blocks": [],
    "timeline_update_suggestions": []
  }
}

Rules:
- The user may write Chinese. Translate it into English search aliases before calling tools.
- Prefer current/latest sources when the query says latest/current/recent.
- Use web_search for both current and historical events.
- rss_search is disabled in this v1 flow.
- Use only tool results. Do not invent URLs.
- Fetch promising URLs before accepting them.
- Unknown domains are rejected by the executor; do not try to bypass the source registry.
- Only accept URLs whose fetch_status is "success"; blocked, failed, or metadata_only pages are diagnostics, not source evidence.
- Keep final compact: only choose accepted_urls. Leave news_blocks and timeline_update_suggestions empty; Python will assemble the final structured news blocks from fetched source_id records.
""".strip()


def _task_prompt(task: TimelineCollectionTask, source_registry: SourceRegistry) -> str:
    return json.dumps(
        {
            "event_query": task.event_query,
            "confirmed_event": task.confirmed_event,
            "confirmed_scope": task.confirmed_scope,
            "baseline_timeline": [item.model_dump(mode="json") for item in task.baseline_timeline],
            "allowed_sources": [
                {
                    "domain": source.domain,
                    "tier": source.source_tier,
                    "type": source.source_type,
                    "region": source.region,
                    "language": source.language,
                }
                for source in source_registry.sources
            ],
            "instruction": "Start by calling web_search with English queries, then fetch useful URLs.",
        },
        ensure_ascii=False,
        indent=2,
    )


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("LLM response must be a JSON object")
    return value


def _candidate_from_result(result, source_meta: SourceEntry, tool: str) -> CandidateSource:
    return CandidateSource(
        url=result.url,
        title=result.title,
        snippet=result.snippet,
        published_at=result.published_at,
        timeline_item_id=None,
        source_tier=source_meta.source_tier,
        source_type=source_meta.source_type,
        publisher=source_meta.domain,
        language=source_meta.language,
        evidence_role="fact_reporting" if source_meta.source_tier in {"P1", "P2"} else "official_statement",
        discovery_method=result.discovery_method or tool,
        collection_pass="discovery_pass",
    )


def _candidate_from_url(url: str, source_meta: SourceEntry) -> CandidateSource:
    return CandidateSource(
        url=url,
        source_tier=source_meta.source_tier,
        source_type=source_meta.source_type,
        publisher=source_meta.domain,
        language=source_meta.language,
        evidence_role="fact_reporting" if source_meta.source_tier in {"P1", "P2"} else "official_statement",
        discovery_method="llm_direct_url",
        collection_pass="discovery_pass",
    )


def _timeline_suggestions_from_final(
    task: TimelineCollectionTask,
    final_payload: dict[str, Any],
    documents: list[SourceDocument],
) -> list[TimelineUpdateSuggestion]:
    url_to_source_id = {_url_key(document.url): document.source_id for document in documents}
    suggestions: list[TimelineUpdateSuggestion] = []
    for index, item in enumerate(final_payload.get("timeline_update_suggestions", []) or [], start=1):
        if not isinstance(item, dict):
            continue
        source_urls = [str(url) for url in item.get("source_urls", [])]
        source_refs = [url_to_source_id[_url_key(url)] for url in source_urls if _url_key(url) in url_to_source_id]
        if not source_refs:
            continue
        suggestions.append(
            TimelineUpdateSuggestion(
                suggestion_id=f"tus_llm_{index:03d}",
                event_id=task.event_id,
                suggested_time_type=item.get("suggested_time_type") or "point",
                suggested_start_date=item.get("suggested_start_date"),
                suggested_end_date=item.get("suggested_end_date"),
                title=str(item.get("title") or "LLM timeline suggestion"),
                reason=str(item.get("reason") or "Suggested by LLM news tool agent."),
                supporting_sources=source_refs,
                suggested_action=item.get("suggested_action") or "add_timeline_item",
            )
        )
    return suggestions


def _tier_summary(documents: list[SourceDocument], source_refs: list[str]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for document in documents:
        if document.source_id not in source_refs:
            continue
        summary[document.source_tier] = summary.get(document.source_tier, 0) + 1
    return summary


def _default_timeline_item_id(task: TimelineCollectionTask) -> str:
    return task.baseline_timeline[0].timeline_item_id if task.baseline_timeline else "tl_001"


def _url_key(url: str) -> str:
    return url.lower().rstrip("/")
