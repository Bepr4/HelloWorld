# 这个文件负责生成新闻搜索词，分别服务时间线定向搜索和范围内补充发现搜索。
from __future__ import annotations

from module1.models import TimelineCollectionTask, TimelineItem


STRONG_EVENT_TERMS = [
    # Discovery Pass 用这些强事件词做补漏，避免只查 baseline_timeline 已有节点。
    "strike",
    "attack",
    "ceasefire",
    "talks",
    "sanctions",
    "retaliation",
    "blockade",
    "agreement",
    "collapse",
]


class QueryBuilder:
    """负责把任务单和时间项转成搜索 query。

    Query 只是发现候选来源的入口，最终能否进入材料库还要经过 SourceRegistry 和 RelevanceJudge。
    """

    def build_site_queries(self, task: TimelineCollectionTask, item: TimelineItem, domain: str) -> list[str]:
        """Timeline Pass 查询：围绕某个已知 timeline_item 查材料。"""

        pieces = [
            f"site:{domain} {task.confirmed_event} {item.title} {item.start_date or ''}".strip(),
            f"site:{domain} {task.confirmed_event} {item.start_date or ''}".strip(),
        ]
        for keyword in item.search_keywords[:4]:
            pieces.append(f"site:{domain} {keyword} {item.start_date or ''}".strip())
        return _dedupe(pieces)

    def build_discovery_queries(self, task: TimelineCollectionTask, domain: str) -> list[str]:
        """Discovery Pass 查询：围绕已确认事件范围做受控补漏。"""

        queries = [f"site:{domain} {task.confirmed_event}"]
        for term in STRONG_EVENT_TERMS:
            queries.append(f"site:{domain} {task.confirmed_event} {term}")
        return _dedupe(queries)


def _dedupe(values: list[str]) -> list[str]:
    """保持顺序去重，避免同一个 query 被重复打给搜索服务。"""

    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        key = " ".join(value.split()).lower()
        if key not in seen:
            seen.add(key)
            output.append(value)
    return output
