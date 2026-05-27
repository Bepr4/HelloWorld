# 这个测试文件验证事件基础信息库能按预期落盘，且 v1 不生成事件地图产物。
import json
from pathlib import Path
from uuid import uuid4

from module1.intake.coordinator import Coordinator
from module1.models import NewsAgentResult, SourceDocument, SourceTextArtifact, TimelineItem
from module1.storage import StorageWriter


def test_storage_writes_event_package_without_context_map():
    output_root = Path("tmp/tests/storage") / uuid4().hex

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
            title="Strike",
            summary="Strike summary",
        )
    ]
    task = Coordinator().build_timeline_collection_task(scope, baseline, event_id="event_storage")
    source = SourceDocument(
        source_id="src_001",
        event_id="event_storage",
        timeline_item_id="tl_001",
        url="https://www.reuters.com/world/example",
        title="Example",
        publisher="reuters.com",
        published_at="2020-01-03",
        fetched_at="2026-05-18T00:00:00+00:00",
        language="en",
        source_tier="P1",
        source_type="wire",
        evidence_role="fact_reporting",
        discovery_method="site_search",
        collection_pass="timeline_pass",
        fetch_status="success",
    )
    news_result = NewsAgentResult(
        source_documents=[source],
        source_texts={"src_001": "source body"},
        source_text_artifacts={
            "src_001": SourceTextArtifact(
                raw_markdown="raw markdown body",
                fit_markdown="fit markdown body",
                cleaned_text="source body",
            )
        },
    )
    storage = StorageWriter(output_root / "module1")

    package = storage.build_event_info_package(
        scope=scope,
        task=task,
        baseline_timeline=baseline,
        news_result=news_result,
        finance_result={"financial_evidence": [], "market_trend_spans": [], "status": "not_implemented"},
    )
    event_dir = storage.save_event_package(
        package,
        source_texts=news_result.source_texts,
        source_text_artifacts=news_result.source_text_artifacts,
    )

    assert (event_dir / "event_info_package.json").exists()
    assert (event_dir / "timeline_collection_task.json").exists()
    assert (event_dir / "baseline_timeline.json").exists()
    assert (event_dir / "sources" / "src_001.txt").read_text(encoding="utf-8") == "source body"
    assert (event_dir / "sources" / "src_001" / "raw_markdown.md").read_text(encoding="utf-8") == "raw markdown body"
    assert (event_dir / "sources" / "src_001" / "fit_markdown.md").read_text(encoding="utf-8") == "fit markdown body"
    assert (event_dir / "sources" / "src_001" / "cleaned_text.txt").read_text(encoding="utf-8") == "source body"

    saved = json.loads((event_dir / "event_info_package.json").read_text(encoding="utf-8"))
    assert "timeline_items" not in saved
    assert "context_map" not in saved
    saved_source = saved["source_documents"][0]
    raw_text_path = saved_source["raw_text_path"].replace("\\", "/")
    raw_markdown_path = saved_source["raw_markdown_path"].replace("\\", "/")
    fit_markdown_path = saved_source["fit_markdown_path"].replace("\\", "/")
    cleaned_text_path = saved_source["cleaned_text_path"].replace("\\", "/")
    assert raw_text_path.endswith("src_001.txt")
    assert raw_markdown_path.endswith("src_001/raw_markdown.md")
    assert fit_markdown_path.endswith("src_001/fit_markdown.md")
    assert cleaned_text_path.endswith("src_001/cleaned_text.txt")
