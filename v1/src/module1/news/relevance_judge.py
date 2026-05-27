# 这个文件负责判断候选新闻是否属于已确认事件范围，并决定是挂到时间线还是提出修正建议。
from __future__ import annotations

from module1.models import RelevanceDecision, SourceDocument, TimelineCollectionTask, TimelineItem
from module1.news.query_builder import STRONG_EVENT_TERMS


class RelevanceJudge:
    """判断候选来源是否属于本轮确认事件范围。

    第一版先用规则判断；后续可以在这里接 AgentClient，让 LLM 做结构化相关性判断。
    """

    def judge_source(
        self,
        source: SourceDocument,
        task: TimelineCollectionTask,
        *,
        text: str = "",
        item: TimelineItem | None = None,
    ) -> RelevanceDecision:
        """对一个 SourceDocument 生成相关性判断。

        Timeline Pass 必须匹配当前时间项；Discovery Pass 可以不匹配已有时间项，
        但需要是确认范围内的重要材料，才会生成时间线修正建议。
        """

        haystack = " ".join(
            value
            for value in [
                source.title or "",
                text,
                source.published_at or "",
            ]
            if value
        ).lower()

        if task.exclude_scope and task.exclude_scope.lower() in haystack:
            return RelevanceDecision(
                is_relevant=False,
                is_in_confirmed_scope=False,
                confidence=0.0,
                reason="Source matches exclude_scope",
            )

        scope_terms = _scope_terms(task)
        in_scope = any(term.lower() in haystack for term in scope_terms)

        matched_item_id = None
        if item is not None and _matches_timeline_item(haystack, item):
            matched_item_id = item.timeline_item_id
        elif source.collection_pass == "discovery_pass":
            for timeline_item in task.baseline_timeline:
                if _matches_timeline_item(haystack, timeline_item):
                    matched_item_id = timeline_item.timeline_item_id
                    break

        important = any(term in haystack for term in STRONG_EVENT_TERMS)
        if item is not None:
            is_relevant = bool(in_scope and matched_item_id == item.timeline_item_id)
        else:
            is_relevant = bool(in_scope and (matched_item_id or important))

        confidence = 0.85 if is_relevant else 0.4
        needs_suggestion = bool(in_scope and source.collection_pass == "discovery_pass" and not matched_item_id and important)

        return RelevanceDecision(
            is_relevant=is_relevant,
            timeline_item_id=matched_item_id,
            matched_existing_timeline_item_id=matched_item_id,
            is_in_confirmed_scope=in_scope,
            needs_timeline_update_suggestion=needs_suggestion,
            confidence=confidence,
            reason="Rule-based relevance decision",
        )


def _scope_terms(task: TimelineCollectionTask) -> list[str]:
    """从任务单里取范围判断关键词。"""

    terms = [task.confirmed_event, task.confirmed_scope, task.event_query]
    return [term for term in terms if term and len(term.strip()) >= 2]


def _matches_timeline_item(haystack: str, item: TimelineItem) -> bool:
    """判断来源是否能挂到某个已有时间项。

    这里刻意只看标题和日期，不用 confirmed_event 这种宽泛词，避免误挂。
    """

    title_hit = item.title.lower() in haystack if item.title else False
    date_hit = item.start_date in haystack if item.start_date else False
    return title_hit or date_hit
