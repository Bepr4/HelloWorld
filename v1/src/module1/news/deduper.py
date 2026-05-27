# 这个文件负责新闻材料去重，主要通过规范化 URL 和正文指纹降低重复来源污染。
from __future__ import annotations

import hashlib
from urllib.parse import urlsplit, urlunsplit

from module1.models import SourceDocument


def normalize_url(url: str) -> str:
    """规范化 URL，去掉 query/fragment，降低重复链接影响。"""

    parts = urlsplit(url)
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def content_hash(text: str) -> str:
    """正文 hash，用于识别重复正文。"""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def source_id_for_url(url: str) -> str:
    """根据 URL 生成稳定 source_id，方便引用和落盘。"""

    return "src_" + hashlib.sha1(normalize_url(url).encode("utf-8")).hexdigest()[:12]


def dedupe_source_documents(documents: list[SourceDocument]) -> list[SourceDocument]:
    """按规范化 URL 和正文 hash 去重。"""

    seen: set[tuple[str, str | None]] = set()
    output: list[SourceDocument] = []
    for document in documents:
        key = (normalize_url(document.url), document.content_hash)
        if key in seen:
            continue
        seen.add(key)
        output.append(document)
    return output
