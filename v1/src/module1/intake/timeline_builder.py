# 这个文件负责从百科类材料中抽取基准时间线，给新闻采集提供初始骨架。
from __future__ import annotations

import re
from dataclasses import dataclass

from module1.intake.wiki_client import EmptyWikiClient, WikiPage
from module1.models import EventScopeConfirmation, TimelineItem


DATE_PATTERNS = [
    # 同时支持 ISO 日期和中文年月日，便于从百科中文/英文材料里抽基准时间线。
    re.compile(r"(?P<year>20\d{2})[-/](?P<month>\d{1,2})[-/](?P<day>\d{1,2})"),
    re.compile(r"(?P<year>20\d{2})\s*年\s*(?P<month>\d{1,2})\s*月\s*(?P<day>\d{1,2})\s*日"),
]


@dataclass
class DatedText:
    """从百科段落里抽出来的“日期 + 原文句子”。"""

    date: str
    text: str
    section_title: str


class TimelineBuilder:
    """把百科/概览资料整理成 baseline_timeline。

    它只生成初始骨架，不判断核心节点，也不生成最终时间线。
    """

    def __init__(self, wiki_client: object | None = None) -> None:
        self.wiki_client = wiki_client or EmptyWikiClient()

    def build_baseline_timeline(self, scope: EventScopeConfirmation, agent_client: object | None = None) -> list[TimelineItem]:
        """构建基准时间线；找不到日期时退化为 background 节点。"""

        page = self.wiki_client.find_event_page(scope.confirmed_event)
        if page is None:
            return self._fallback_timeline(scope)

        dated_items = extract_dated_items(page)
        if not dated_items:
            return self._fallback_timeline(scope, page)

        timeline: list[TimelineItem] = []
        for index, item in enumerate(sorted(dated_items, key=lambda x: x.date), start=1):
            timeline.append(
                TimelineItem(
                    timeline_item_id=f"tl_{index:03d}",
                    time_type="point",
                    start_date=item.date,
                    title=_title_from_text(item.text),
                    summary=item.text,
                    source_hint=page.url or page.title,
                    search_keywords=_keywords(scope.confirmed_event, item.text),
                )
            )
        return timeline

    def _fallback_timeline(
        self,
        scope: EventScopeConfirmation,
        page: WikiPage | None = None,
    ) -> list[TimelineItem]:
        """没有百科页或没有日期时，至少保留一个背景项，保证后续任务能继续跑。"""

        hint = page.url or page.title if page else None
        return [
            TimelineItem(
                timeline_item_id="tl_001",
                time_type="background",
                title=scope.confirmed_event,
                summary=scope.confirmed_scope,
                source_hint=hint,
                search_keywords=[scope.confirmed_event],
            )
        ]


def extract_dated_items(page: WikiPage) -> list[DatedText]:
    """从 WikiPage 的所有 section 中抽取带日期的句子。"""

    items: list[DatedText] = []
    for section in page.sections:
        for sentence in _split_text(section.text):
            for normalized in _find_dates(sentence):
                items.append(DatedText(date=normalized, text=sentence.strip(), section_title=section.title))
    return items


def _split_text(text: str) -> list[str]:
    """按句号、中文句号、换行做一个足够轻量的切句。"""

    chunks = re.split(r"(?<=[。.!?])\s+|\n+", text)
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def _find_dates(text: str) -> list[str]:
    """把句子里的日期统一归一成 YYYY-MM-DD。"""

    dates: list[str] = []
    for pattern in DATE_PATTERNS:
        for match in pattern.finditer(text):
            year = int(match.group("year"))
            month = int(match.group("month"))
            day = int(match.group("day"))
            dates.append(f"{year:04d}-{month:02d}-{day:02d}")
    return dates


def _title_from_text(text: str) -> str:
    """第一版直接用原句前 80 个字符当时间项标题。"""

    clean = re.sub(r"\s+", " ", text).strip()
    return clean[:80]


def _keywords(event_name: str, text: str) -> list[str]:
    """生成少量起始关键词；它们只是检索线索，不是采集边界。"""

    words = [event_name]
    for token in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", text):
        if token.lower() not in {w.lower() for w in words}:
            words.append(token)
        if len(words) >= 6:
            break
    return words
