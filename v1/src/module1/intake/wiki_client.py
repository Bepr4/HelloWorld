# 这个文件定义百科页面读取接口；v1 提供空实现和静态实现，方便后续接 Wikipedia API。
from __future__ import annotations

from pydantic import BaseModel, Field


class WikiSection(BaseModel):
    """百科页面中的一个小节。"""

    title: str
    text: str


class WikiPage(BaseModel):
    """WikiClient 返回的页面结构。

    第一版只需要标题、URL 和正文小节，后续再扩展 MediaWiki 元数据。
    """

    title: str
    url: str | None = None
    sections: list[WikiSection] = Field(default_factory=list)


class StaticWikiClient:
    """测试用 WikiClient，从内存字典返回页面。"""

    def __init__(self, pages: dict[str, WikiPage] | None = None) -> None:
        self.pages = pages or {}

    def find_event_page(self, confirmed_event: str) -> WikiPage | None:
        if confirmed_event in self.pages:
            return self.pages[confirmed_event]
        if self.pages:
            return next(iter(self.pages.values()))
        return None


class EmptyWikiClient:
    """默认空客户端；没有百科数据时让 TimelineBuilder 走 fallback。"""

    def find_event_page(self, confirmed_event: str) -> WikiPage | None:
        return None
