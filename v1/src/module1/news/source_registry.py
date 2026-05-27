# 这个文件读取和匹配权威来源白名单，控制哪些新闻域名可以进入模块一材料层。
from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel


class SourceEntry(BaseModel):
    """一条可用来源配置。

    只有在 SourceRegistry 里的域名才允许进入事件基础信息库。
    """

    domain: str
    source_tier: Literal["P0", "P1", "P2", "P3"]
    source_type: str
    region: str | None = None
    language: str | None = None
    core_evidence_allowed: bool = True


class SourceRegistry:
    """P0-P3 来源注册表。

    它是信息层的第一道闸门：搜索引擎只能发现 URL，不能决定来源是否可用。
    """

    def __init__(self, sources: list[SourceEntry]) -> None:
        self.sources = sources

    @classmethod
    def from_yaml(cls, path: str | Path) -> "SourceRegistry":
        """读取 source_registry.yaml。

        为了减少第一版依赖，这里实现了一个只支持当前配置格式的轻量 YAML 解析器。
        """

        text = Path(path).read_text(encoding="utf-8")
        return cls(_parse_sources_yaml(text))

    def match(self, url: str) -> SourceEntry | None:
        """按域名匹配来源配置，支持 www.reuters.com -> reuters.com。"""

        hostname = urlparse(url).hostname or ""
        hostname = hostname.lower().removeprefix("www.")
        for source in self.sources:
            domain = source.domain.lower().removeprefix("www.")
            if hostname == domain or hostname.endswith(f".{domain}"):
                return source
        return None

    def domains_for_tier(self, tier: str) -> list[str]:
        """返回某个来源等级下的全部域名，用于 site: 查询。"""

        return [source.domain for source in self.sources if source.source_tier == tier]


def _parse_sources_yaml(text: str) -> list[SourceEntry]:
    """解析本项目固定格式的 sources 列表。"""

    sources: list[dict] = []
    current: dict | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line == "sources:":
            continue
        if line.startswith("- "):
            if current:
                sources.append(current)
            current = {}
            line = line[2:].strip()
            if line:
                key, value = line.split(":", 1)
                current[key.strip()] = _coerce_yaml_value(value.strip())
            continue
        if current is not None and ":" in line:
            key, value = line.split(":", 1)
            current[key.strip()] = _coerce_yaml_value(value.strip())

    if current:
        sources.append(current)
    return [SourceEntry.model_validate(item) for item in sources]


def _coerce_yaml_value(value: str):
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    return value.strip('"').strip("'")
