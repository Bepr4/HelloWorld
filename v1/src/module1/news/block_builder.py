# 这个文件把已通过相关性判断的来源材料聚合成新闻事件块，供事件基础信息库保存。
from __future__ import annotations

from collections import Counter, defaultdict

from module1.models import NewsBlock, SourceDocument, TimelineCollectionTask
from module1.news.text_cleaner import first_meaningful_excerpt


class NewsBlockBuilder:
    """把多个来源整理成按 timeline_item_id 聚合的 NewsBlock。"""

    def build_news_blocks(
        self,
        task: TimelineCollectionTask,
        documents: list[SourceDocument],
        source_texts: dict[str, str],
    ) -> list[NewsBlock]:
        """只使用成功抓取且已经挂到 timeline_item_id 的来源生成新闻块。"""

        grouped: dict[str, list[SourceDocument]] = defaultdict(list)
        for document in documents:
            if document.fetch_status != "success" or not document.timeline_item_id:
                continue
            grouped[document.timeline_item_id].append(document)

        blocks: list[NewsBlock] = []
        for index, (timeline_item_id, docs) in enumerate(sorted(grouped.items()), start=1):
            title = docs[0].title or f"News for {timeline_item_id}"
            refs = [doc.source_id for doc in docs]
            tier_counts = Counter(doc.source_tier for doc in docs)
            summaries = [
                {
                    "source_id": doc.source_id,
                    "summary": _source_excerpt(source_texts.get(doc.source_id, "")) or doc.title or "",
                }
                for doc in docs
            ]
            reported_facts = [
                {
                    "source_id": doc.source_id,
                    "text": _source_excerpt(source_texts.get(doc.source_id, "")) or doc.title or "",
                }
                for doc in docs
            ]
            blocks.append(
                NewsBlock(
                    news_block_id=f"nb_{index:03d}",
                    event_id=task.event_id,
                    timeline_item_id=timeline_item_id,
                    title=title,
                    summary=_block_summary(summaries),
                    event_time=_event_time_for(task, timeline_item_id),
                    reported_facts=reported_facts,
                    source_summaries=summaries,
                    source_differences=[],
                    source_refs=refs,
                    source_tier_summary=dict(tier_counts),
                )
            )
        return blocks


def _first_sentence(text: str) -> str:
    """抽取一个短句作为第一版摘要/报道事实。"""

    if not text:
        return ""
    for delimiter in [". ", "。", "\n"]:
        if delimiter in text:
            return text.split(delimiter, 1)[0].strip() + ("." if delimiter == ". " else "")
    return text.strip()[:240]


def _source_excerpt(text: str) -> str:
    """从来源正文中提取真正像新闻事实的片段，避免把导航和分享文案写进摘要。"""

    return first_meaningful_excerpt(text, limit=520)


def _block_summary(summaries: list[dict[str, str]]) -> str:
    """合并多个来源摘要时保留可读的短句，而不是拼接整段网页 markdown。"""

    parts = [item["summary"] for item in summaries if item.get("summary")]
    return " ".join(parts)[:900]


def _event_time_for(task: TimelineCollectionTask, timeline_item_id: str) -> str | None:
    """从 baseline_timeline 中找新闻块对应的事件时间。"""

    for item in task.baseline_timeline:
        if item.timeline_item_id == timeline_item_id:
            return item.start_date
    return None
