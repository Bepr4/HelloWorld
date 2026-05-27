# 这个文件负责清洗网页抓取后的正文文本，去掉导航、分享按钮、推荐阅读等噪声，给后续摘要和存储使用。
from __future__ import annotations

import re


_EXACT_NOISE_LINES = {
    "read more",
    "share",
    "copy",
    "link copied",
    "print",
    "save",
    "or use",
    "advertisement",
    "listen",
    "listenlisten",
}

_NOISE_PATTERNS = [
    re.compile(r"^#+\s*login or register to continue$", re.IGNORECASE),
    re.compile(r"^add ap news on google", re.IGNORECASE),
    re.compile(r"^googleadd .* on google", re.IGNORECASE),
    re.compile(r"^recommended stories$", re.IGNORECASE),
    re.compile(r"^\d+\s+of\s+\d+(\s*\|)?$", re.IGNORECASE),
    re.compile(r"^\[[^\]]+\]\(https?://[^)]+\)$"),
    re.compile(r"^!\[[\s\S]*\]\(https?://[^)]+\)$"),
    re.compile(r"^\*\s*\[[^\]]+\]\(https?://[^)]+\)$"),
    re.compile(r"^\[[^\]]*\]\(https?://[^)]+\)$"),
]


def clean_article_text(text: str) -> str:
    """清理 Crawl4AI 返回的 markdown / 文本，保留正文段落并压掉常见站点噪声。"""

    if not text:
        return ""

    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    cleaned: list[str] = []
    skipping_recommendations = False
    previous = ""

    for line in lines:
        if not line:
            if cleaned and cleaned[-1]:
                cleaned.append("")
            continue

        lowered = line.lower().strip()
        if lowered.startswith("## recommended stories") or lowered == "recommended stories":
            skipping_recommendations = True
            continue
        if skipping_recommendations:
            if line.startswith("* ") or line.startswith("- ") or re.match(r"^\[[^\]]+\]\(https?://", line):
                continue
            skipping_recommendations = False

        if _is_noise_line(line):
            continue
        if line == previous:
            continue

        cleaned.append(line)
        previous = line

    return _compact_blank_lines("\n".join(cleaned)).strip()


def first_meaningful_excerpt(text: str, *, limit: int = 520) -> str:
    """从清洗后的文本中抽取一个适合进入 news block 的短摘要片段。"""

    cleaned = clean_article_text(text)
    if not cleaned:
        return ""

    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n{2,}", cleaned) if paragraph.strip()]
    candidates = []
    for paragraph in paragraphs:
        normalized = re.sub(r"^#+\s*", "", paragraph).strip()
        if len(normalized) < 80:
            continue
        if normalized.lower() in _EXACT_NOISE_LINES:
            continue
        candidates.append(normalized)

    excerpt = candidates[0] if candidates else re.sub(r"^#+\s*", "", paragraphs[0]).strip()
    return _truncate_at_sentence(excerpt, limit)


def _is_noise_line(line: str) -> bool:
    lowered = line.lower().strip()
    if lowered in _EXACT_NOISE_LINES:
        return True
    return any(pattern.search(line) for pattern in _NOISE_PATTERNS)


def _compact_blank_lines(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text)
    return re.sub(r"[ \t]+", " ", text)


def _truncate_at_sentence(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    window = text[:limit]
    sentence_end = max(window.rfind(". "), window.rfind("。"), window.rfind("! "), window.rfind("? "))
    if sentence_end >= 160:
        return window[: sentence_end + 1].strip()
    return window.rstrip() + "..."
