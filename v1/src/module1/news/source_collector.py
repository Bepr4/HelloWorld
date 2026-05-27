# 这个文件负责从搜索结果中收集候选新闻源，并用来源白名单过滤掉未知或低可信来源。
from __future__ import annotations

from typing import Protocol

from module1.models import CandidateSource, SearchResult, TimelineCollectionTask, TimelineItem
from module1.news.query_builder import QueryBuilder
from module1.news.source_registry import SourceEntry, SourceRegistry


class SearchProvider(Protocol):
    """搜索服务接口。

    真实搜索 API 和测试用静态搜索都只需要实现 search(queries)。
    """

    def search(self, queries: list[str]) -> list[SearchResult]:
        ...


class StaticSearchProvider:
    """测试用搜索服务，不联网，直接返回内存里的 SearchResult。"""

    def __init__(self, results: list[SearchResult] | dict[str, list[SearchResult]] | None = None) -> None:
        self.results = results or []

    def search(self, queries: list[str]) -> list[SearchResult]:
        if isinstance(self.results, list):
            return self.results
        output: list[SearchResult] = []
        for query in queries:
            output.extend(self.results.get(query, []))
        return output


class SourceCollector:
    """负责发现候选 URL，并用 SourceRegistry 做来源等级过滤。"""

    def __init__(
        self,
        source_registry: SourceRegistry,
        search_provider: SearchProvider,
        query_builder: QueryBuilder | None = None,
    ) -> None:
        self.source_registry = source_registry
        self.search_provider = search_provider
        self.query_builder = query_builder or QueryBuilder()

    def collect_for_timeline_item(
        self,
        task: TimelineCollectionTask,
        item: TimelineItem,
    ) -> list[CandidateSource]:
        """Timeline Pass：围绕一个基准时间项查 P0-P3 来源。"""

        candidates: list[CandidateSource] = []

        for tier in ["P0", "P1", "P2", "P3"]:
            for domain in self.source_registry.domains_for_tier(tier):
                queries = self.query_builder.build_site_queries(task, item, domain)
                for result in self.search_provider.search(queries):
                    source_meta = self.source_registry.match(result.url)
                    if not source_meta:
                        continue
                    candidates.append(_candidate_from_result(result, source_meta, item.timeline_item_id, "timeline_pass"))

            if _enough_sources(candidates):
                break

        return _dedupe_candidates(candidates)

    def collect_for_discovery(self, task: TimelineCollectionTask) -> list[CandidateSource]:
        """Discovery Pass：不绑定具体时间项，但仍只允许 P0-P3 来源。"""

        candidates: list[CandidateSource] = []

        for tier in ["P0", "P1", "P2", "P3"]:
            tier_count = 0
            for domain in self.source_registry.domains_for_tier(tier):
                queries = self.query_builder.build_discovery_queries(task, domain)
                for result in self.search_provider.search(queries):
                    source_meta = self.source_registry.match(result.url)
                    if not source_meta:
                        continue
                    candidates.append(_candidate_from_result(result, source_meta, None, "discovery_pass"))
                    tier_count += 1
                    if tier_count >= 10:
                        break
                if tier_count >= 10:
                    break

        return _dedupe_candidates(candidates)


def _candidate_from_result(
    result: SearchResult,
    source_meta: SourceEntry,
    timeline_item_id: str | None,
    collection_pass: str,
) -> CandidateSource:
    """把搜索结果和来源配置合并成 CandidateSource。"""

    return CandidateSource(
        url=result.url,
        title=result.title,
        snippet=result.snippet,
        published_at=result.published_at,
        timeline_item_id=timeline_item_id,
        source_tier=source_meta.source_tier,
        source_type=source_meta.source_type,
        publisher=source_meta.domain,
        language=source_meta.language,
        evidence_role="fact_reporting" if source_meta.source_tier in {"P1", "P2"} else "official_statement",
        discovery_method=result.discovery_method or "site_search",
        collection_pass=collection_pass,  # type: ignore[arg-type]
    )


def _enough_sources(candidates: list[CandidateSource]) -> bool:
    """控制 Timeline Pass 的采集规模。

    这不是事实确认，只是避免 P0/P1 已足够时继续引入大量低优先级噪音。
    """

    p0_count = sum(1 for candidate in candidates if candidate.source_tier == "P0")
    p1_count = sum(1 for candidate in candidates if candidate.source_tier == "P1")
    return p0_count >= 1 or p1_count >= 2


def _dedupe_candidates(candidates: list[CandidateSource]) -> list[CandidateSource]:
    """按 URL 去重，避免同一个结果被多个 query 重复发现。"""

    seen: set[str] = set()
    output: list[CandidateSource] = []
    for candidate in candidates:
        key = candidate.url.lower().rstrip("/")
        if key not in seen:
            seen.add(key)
            output.append(candidate)
    return output
