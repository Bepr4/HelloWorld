# 这个文件负责判断抓取到的网页正文是否像可引用新闻正文，输入 URL/标题/正文，输出是否应进入材料包。
from __future__ import annotations

import re
from urllib.parse import urlparse


_INDEX_PATH_MARKERS = (
    "/news/topics/",
    "/topics/",
    "/tag/",
    "/tags/",
    "/hub/",
    "/search",
)

_NOISY_TEXT_MARKERS = (
    "followfollowfollowingfollowingunfollowunfollow",
    "you are now following",
    "updates from your news topics",
    "site search\nnews\nbusiness\ntechnology",
)


def source_quality_issue(url: str, title: str | None, text: str) -> str | None:
    """返回质量问题说明；没有问题时返回 None。"""

    normalized_text = (text or "").strip()
    if not normalized_text:
        return "empty_text"

    path = urlparse(url).path.lower()
    if any(marker in path for marker in _INDEX_PATH_MARKERS):
        return "index_or_topic_page"

    lowered = normalized_text.lower()
    if any(marker in lowered for marker in _NOISY_TEXT_MARKERS):
        return "navigation_or_topic_noise"

    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'’.-]*", normalized_text)
    if len(words) < 80:
        return "too_short"

    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n{2,}", normalized_text) if paragraph.strip()]
    article_like_paragraphs = [
        paragraph
        for paragraph in paragraphs
        if len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'’.-]*", paragraph)) >= 25
    ]
    if len(article_like_paragraphs) < 2 and len(words) < 180:
        return "not_enough_article_paragraphs"

    if _link_or_menu_line_ratio(normalized_text) > 0.45:
        return "high_navigation_density"

    if title and normalized_text.count(title.strip()) >= 3:
        return "repeated_title_noise"

    return None


def _link_or_menu_line_ratio(text: str) -> float:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return 1.0
    noisy = 0
    for line in lines:
        word_count = len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'’.-]*", line))
        if word_count <= 2:
            noisy += 1
        elif line.startswith(("* ", "- ", "• ")):
            noisy += 1
        elif line.startswith("[") and "](" in line:
            noisy += 1
    return noisy / len(lines)
