# 这个文件负责给网页抓取器补充事件上下文，让 Crawl4AI 可以按当前事件主题清洗正文，同时兼容旧的 fetch(url) 测试接口。
from __future__ import annotations

import inspect
import re
from typing import Any

from module1.models import CandidateSource, FetchedPage, TimelineCollectionTask, TimelineItem


def build_fetch_query(
    task: TimelineCollectionTask,
    candidate: CandidateSource,
    *,
    item: TimelineItem | None = None,
    max_length: int = 900,
) -> str:
    """把事件范围、时间线节点和候选来源摘要合成 BM25 可使用的短查询。"""

    parts: list[str | None] = [
        task.confirmed_event,
        task.confirmed_scope,
        task.event_query,
    ]
    if item is not None:
        parts.extend([item.title, item.summary, *item.search_keywords])
    parts.extend([candidate.title, candidate.snippet])
    return _compact_query(parts, max_length=max_length)


def fetch_with_query(fetcher: object, url: str, query: str | None) -> FetchedPage:
    """优先调用 fetch(url, query=...)，旧抓取器不支持 query 时自动退回 fetch(url)。"""

    fetch = getattr(fetcher, "fetch")
    if _callable_accepts_keyword(fetch, "query"):
        return fetch(url, query=query)
    return fetch(url)


def _compact_query(values: list[str | None], *, max_length: int) -> str:
    seen: set[str] = set()
    output: list[str] = []
    current_length = 0
    for value in values:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        projected_length = current_length + len(text) + (1 if output else 0)
        if projected_length > max_length:
            remaining = max_length - current_length - (1 if output else 0)
            if remaining > 40:
                output.append(text[:remaining].rstrip())
            break
        output.append(text)
        current_length = projected_length
    return " ".join(output)


def _callable_accepts_keyword(func: Any, keyword: str) -> bool:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return False
    for parameter in signature.parameters.values():
        if parameter.kind == inspect.Parameter.VAR_KEYWORD:
            return True
    return keyword in signature.parameters
