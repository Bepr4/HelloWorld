# 这个文件负责把模块一产物写入磁盘，包括事件包 JSON、任务单、时间线和原文文本。
from __future__ import annotations

import json
from pathlib import Path

from module1.models import EventInfoPackage, EventScopeConfirmation, NewsAgentResult, TimelineCollectionTask, TimelineItem


class StorageWriter:
    """负责把事件基础信息库写成 JSON 文件和原文 txt 文件。"""

    def __init__(self, storage_root: str | Path) -> None:
        self.storage_root = Path(storage_root)

    def build_event_info_package(
        self,
        *,
        scope: EventScopeConfirmation,
        task: TimelineCollectionTask,
        baseline_timeline: list[TimelineItem],
        news_result: NewsAgentResult,
        finance_result: dict,
    ) -> EventInfoPackage:
        """把各 Agent 产物组装成第一版最终事件材料包。"""

        return EventInfoPackage(
            event_id=task.event_id,
            event_query=scope.event_query,
            confirmed_event=scope.confirmed_event,
            confirmed_scope=scope.confirmed_scope,
            timeline_collection_task=task,
            baseline_timeline=baseline_timeline,
            news_blocks=news_result.news_blocks,
            timeline_update_suggestions=news_result.timeline_update_suggestions,
            financial_evidence=finance_result.get("financial_evidence", []),
            market_trend_spans=finance_result.get("market_trend_spans", []),
            source_documents=news_result.source_documents,
            entities=[],
            locations=[],
            evidence_refs=_build_evidence_refs(news_result),
        )

    def save_event_package(
        self,
        package: EventInfoPackage,
        *,
        source_texts: dict[str, str] | None = None,
    ) -> Path:
        """将事件材料包落盘。

        成功抓到正文的来源会写入 sources/<source_id>.txt，并把路径回填到 SourceDocument。
        """

        event_dir = self.storage_root / "events" / package.event_id
        sources_dir = event_dir / "sources"
        sources_dir.mkdir(parents=True, exist_ok=True)

        source_texts = source_texts or {}
        for document in package.source_documents:
            if document.source_id not in source_texts:
                continue
            source_path = sources_dir / f"{document.source_id}.txt"
            source_path.write_text(source_texts[document.source_id], encoding="utf-8")
            document.raw_text_path = str(source_path)

        self._write_json(event_dir / "event_info_package.json", package.model_dump(mode="json"))
        self._write_json(
            event_dir / "timeline_collection_task.json",
            package.timeline_collection_task.model_dump(mode="json"),
        )
        self._write_json(
            event_dir / "baseline_timeline.json",
            [item.model_dump(mode="json") for item in package.baseline_timeline],
        )
        return event_dir

    @staticmethod
    def _write_json(path: Path, data) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_evidence_refs(news_result: NewsAgentResult) -> list[dict]:
    """生成轻量证据索引，方便后续从新闻块或时间线建议反查来源。"""

    refs: list[dict] = []
    for block in news_result.news_blocks:
        for source_id in block.source_refs:
            refs.append(
                {
                    "ref_id": f"{block.news_block_id}:{source_id}",
                    "news_block_id": block.news_block_id,
                    "source_id": source_id,
                }
            )
    for suggestion in news_result.timeline_update_suggestions:
        for source_id in suggestion.supporting_sources:
            refs.append(
                {
                    "ref_id": f"{suggestion.suggestion_id}:{source_id}",
                    "suggestion_id": suggestion.suggestion_id,
                    "source_id": source_id,
                }
            )
    return refs
