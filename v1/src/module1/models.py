# 这个文件集中定义模块一所有结构化数据模型，用 Pydantic 校验 JSON 落盘格式。
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Module1Model(BaseModel):
    """模块一所有结构化对象的基类。

    extra="forbid" 的意思是：模型里没有定义的字段不允许偷偷混进来。
    这能防止 LLM 或采集器输出脏字段后直接写入事件材料包。
    """

    model_config = ConfigDict(extra="forbid")


class EventScopeConfirmation(Module1Model):
    """用户确认后的事件范围。

    第一版必须先得到这个对象，并且 user_confirmed=True，后续时间线和新闻采集才能启动。
    """

    event_query: str
    confirmed_event: str
    confirmed_scope: str
    time_range: str | None = None
    locations: list[str] = Field(default_factory=list)
    key_actors: list[str] = Field(default_factory=list)
    exclude_scope: str | None = None
    background_rule: str | None = None
    user_confirmed: bool


class TimelineItem(Module1Model):
    """基准事件时间线中的一个时间项。

    point 表示单日事件，interval 表示区间事件，background 只作为背景材料。
    """

    timeline_item_id: str
    time_type: Literal["point", "interval", "background"]
    start_date: str | None = None
    end_date: str | None = None
    title: str
    summary: str
    actors: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    source_hint: str | None = None
    search_keywords: list[str] = Field(default_factory=list)


class TimelineCollectionTask(Module1Model):
    """统筹 Agent 交给新闻 Agent / 金融 Agent 的内部任务单。

    第一版只保留最小字段，核心是让所有采集都围绕同一个 confirmed_scope 和 baseline_timeline。
    """

    event_id: str
    event_query: str
    confirmed_event: str
    confirmed_scope: str
    baseline_timeline: list[TimelineItem]
    exclude_scope: str | None = None
    news_task: str
    finance_task: str | None = None


class SourceDocument(Module1Model):
    """进入事件基础信息库的原始来源记录。

    这里记录的是来源元数据和正文路径，不保存 API Key，也不承担最终事实裁判。
    """

    source_id: str
    event_id: str
    timeline_item_id: str | None = None
    url: str
    title: str | None = None
    publisher: str | None = None
    published_at: str | None = None
    fetched_at: str
    language: str | None = None
    source_tier: Literal["P0", "P1", "P2", "P3"]
    source_type: str
    evidence_role: str
    discovery_method: str
    collection_pass: Literal["timeline_pass", "discovery_pass"] = "timeline_pass"
    content_hash: str | None = None
    raw_text_path: str | None = None
    fetch_status: Literal["success", "metadata_only", "blocked", "failed"]
    fetch_error: str | None = None
    relevance_score: float | None = None


class NewsBlock(Module1Model):
    """按 timeline_item_id 聚合出来的新闻事件块。

    reported_facts 只表示“来源中这样报道”，不是系统最终确认事实。
    """

    news_block_id: str
    event_id: str
    timeline_item_id: str
    title: str
    summary: str
    event_time: str | None = None
    locations: list[str] = Field(default_factory=list)
    actors: list[str] = Field(default_factory=list)
    reported_facts: list[dict[str, Any]] = Field(default_factory=list)
    source_summaries: list[dict[str, Any]] = Field(default_factory=list)
    source_differences: list[dict[str, Any]] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    source_tier_summary: dict[str, int] = Field(default_factory=dict)


class TimelineUpdateSuggestion(Module1Model):
    """新闻 Agent 对基准时间线的修正建议。

    新闻 Agent 不能直接修改 baseline_timeline，只能把新增、合并或改日期建议写到这里。
    """

    suggestion_id: str
    event_id: str
    suggested_time_type: Literal["point", "interval"] = "point"
    suggested_start_date: str | None = None
    suggested_end_date: str | None = None
    title: str
    reason: str
    supporting_sources: list[str]
    suggested_action: Literal[
        "add_timeline_item",
        "merge_timeline_item",
        "adjust_date",
    ]


class EventInfoPackage(Module1Model):
    """模块一第一版的最终落盘对象。

    第一版不生成 Context Map，也不生成最终时间线；事件基础信息库写到这里就算成功。
    """

    event_id: str
    event_query: str
    confirmed_event: str
    confirmed_scope: str
    timeline_collection_task: TimelineCollectionTask
    baseline_timeline: list[TimelineItem]
    news_blocks: list[NewsBlock] = Field(default_factory=list)
    timeline_update_suggestions: list[TimelineUpdateSuggestion] = Field(default_factory=list)
    financial_evidence: list[dict[str, Any]] = Field(default_factory=list)
    market_trend_spans: list[dict[str, Any]] = Field(default_factory=list)
    source_documents: list[SourceDocument] = Field(default_factory=list)
    entities: list[dict[str, Any]] = Field(default_factory=list)
    locations: list[dict[str, Any]] = Field(default_factory=list)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)


class SearchResult(Module1Model):
    """搜索服务返回的原始候选结果。

    它还不是可用来源，必须先经过 SourceRegistry 判断来源等级。
    """

    url: str
    title: str | None = None
    snippet: str | None = None
    published_at: str | None = None
    discovery_method: str | None = None


class CandidateSource(Module1Model):
    """通过 SourceRegistry 过滤后的候选来源。

    CandidateSource 还没抓正文，也还没做相关性判断。
    """

    url: str
    title: str | None = None
    snippet: str | None = None
    published_at: str | None = None
    timeline_item_id: str | None = None
    source_tier: Literal["P0", "P1", "P2", "P3"]
    source_type: str
    publisher: str | None = None
    language: str | None = None
    evidence_role: str
    discovery_method: str
    collection_pass: Literal["timeline_pass", "discovery_pass"]


class FetchedPage(Module1Model):
    """Fetcher 抓取后的网页内容。

    metadata_only 和 failed 可以保留为线索，但不能用来生成 reported_facts。
    """

    url: str
    title: str | None = None
    text: str | None = None
    published_at: str | None = None
    status: Literal["success", "metadata_only", "blocked", "failed"]
    error: str | None = None


class RelevanceDecision(Module1Model):
    """RelevanceJudge 对一个来源是否可纳入本轮事件的判断结果。"""

    is_relevant: bool
    timeline_item_id: str | None = None
    matched_existing_timeline_item_id: str | None = None
    is_in_confirmed_scope: bool
    needs_timeline_update_suggestion: bool = False
    confidence: float
    reason: str


class NewsAgentResult(Module1Model):
    """新闻 Agent 的完整输出，供 StorageWriter 写入事件基础信息库。"""

    source_documents: list[SourceDocument] = Field(default_factory=list)
    news_blocks: list[NewsBlock] = Field(default_factory=list)
    timeline_update_suggestions: list[TimelineUpdateSuggestion] = Field(default_factory=list)
    source_texts: dict[str, str] = Field(default_factory=dict)
