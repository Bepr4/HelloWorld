# 这个文件负责把模块一产物写入磁盘，包括事件包 JSON、任务单、时间线和原文文本。
from __future__ import annotations

import json
from pathlib import Path

from module1.models import (
    EventInfoPackage,
    EventScopeConfirmation,
    NewsAgentResult,
    SourceTextArtifact,
    TimelineCollectionTask,
    TimelineItem,
)


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
        source_text_artifacts: dict[str, SourceTextArtifact] | None = None,
    ) -> Path:
        """将事件材料包落盘。

        成功抓到正文的来源会继续写入旧的 sources/<source_id>.txt；
        同时写出 raw_markdown / fit_markdown / cleaned_text 三份对比文件，方便验证清洗效果。
        """

        event_dir = self.storage_root / "events" / package.event_id
        sources_dir = event_dir / "sources"
        sources_dir.mkdir(parents=True, exist_ok=True)

        source_texts = source_texts or {}
        source_text_artifacts = source_text_artifacts or {}
        for document in package.source_documents:
            artifact = _artifact_for_source(
                source_text_artifacts.get(document.source_id),
                cleaned_text=source_texts.get(document.source_id),
            )
            if artifact is None:
                continue

            # 旧路径暂时保留为 cleaned_text 的兼容副本，后面清洗稳定后可以删除。
            if artifact.cleaned_text is not None:
                source_path = sources_dir / f"{document.source_id}.txt"
                source_path.write_text(artifact.cleaned_text, encoding="utf-8")
                document.raw_text_path = str(source_path)

            source_dir = sources_dir / document.source_id
            raw_path = _write_optional_text(source_dir / "raw_markdown.md", artifact.raw_markdown)
            fit_path = _write_optional_text(source_dir / "fit_markdown.md", artifact.fit_markdown)
            cleaned_path = _write_optional_text(source_dir / "cleaned_text.txt", artifact.cleaned_text)
            document.raw_markdown_path = str(raw_path) if raw_path else None
            document.fit_markdown_path = str(fit_path) if fit_path else None
            document.cleaned_text_path = str(cleaned_path) if cleaned_path else None

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


def _artifact_for_source(
    artifact: SourceTextArtifact | None,
    *,
    cleaned_text: str | None,
) -> SourceTextArtifact | None:
    """兼容旧调用：没有三层 artifact 时，用 source_texts 里的正文补 cleaned_text。"""

    if artifact is None and cleaned_text is None:
        return None
    if artifact is None:
        return SourceTextArtifact(cleaned_text=cleaned_text)
    if artifact.cleaned_text is None and cleaned_text is not None:
        return artifact.model_copy(update={"cleaned_text": cleaned_text})
    return artifact


def _write_optional_text(path: Path, text: str | None) -> Path | None:
    """有内容才写文件，避免为缺失的 Crawl4AI 层制造空对比文件。"""

    if text is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
