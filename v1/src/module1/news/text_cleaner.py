# 这个文件负责清洗网页抓取后的正文文本，去掉导航、分享按钮、推荐阅读等噪声，给后续摘要和存储使用。
from __future__ import annotations

import re


_EXACT_NOISE_LINES = {
    "read more",
    "share",
    "share-nodes",
    "copy",
    "link copied",
    "print",
    "save",
    "or use",
    "advertisement",
    "listen",
    "listenlisten",
    "listenlisten (7 mins)",
    "listenlisten (8 mins)",
    "site search",
    "latest news",
    "news",
    "business",
    "technology",
    "culture",
    "arts",
    "travel",
    "earth",
    "audio",
    "video",
    "live",
    "world news",
    "sign in with google. opens in new tab",
    "leer en español",
    "comments",
    "linkedin",
    "* linkedin",
    "defend press freedom",
    "view illustrations",
    "list of iab vendors",
    "back button",
    "vendors list",
    "search icon",
    "filter icon",
    "clear",
    "apply cancel",
    "consent leg.interest",
    "confirm my choices",
    "i reject all",
    "allowmanage cookie preferences",
    "yes, keep me updated",
    "audio-rewind",
    "audio-play",
    "audio-forward",
    "your browser does not support the audio element.",
    "getty images",
}

_NOISE_PATTERNS = [
    re.compile(r"^#+\s*login or register to continue$", re.IGNORECASE),
    re.compile(r"^add ap news on google", re.IGNORECASE),
    re.compile(r"^googleadd .* on google", re.IGNORECASE),
    re.compile(r"^recommended stories$", re.IGNORECASE),
    re.compile(r"^[▶▷\s_*.-]*read more\.?[▶▷\s_*.-]*$", re.IGNORECASE),
    re.compile(r"^[*_▶▷\s.-]*read more\b.*$", re.IGNORECASE),
    re.compile(r"^sign in with google", re.IGNORECASE),
    re.compile(r"^\*\s*linkedin$", re.IGNORECASE),
    re.compile(r"^leer en español$", re.IGNORECASE),
    re.compile(r"^comments$", re.IGNORECASE),
    re.compile(r"^updated\s+\[hour\]:\[minute\]", re.IGNORECASE),
    re.compile(r"^\*{0,2}0\*{0,2}$"),
    re.compile(r"^listenlisten\s*\(\d+\s+mins?\)$", re.IGNORECASE),
    re.compile(r"^follow ap.?s live updates\b", re.IGNORECASE),
    re.compile(r"^#+\s*this content is unavailable due to your cookie settings\.?$", re.IGNORECASE),
    re.compile(r"^this content is unavailable due to your cookie settings\.?$", re.IGNORECASE),
    re.compile(r"^to continue, please allow functional cookies\b", re.IGNORECASE),
    re.compile(r"^allowmanage cookie preferences$", re.IGNORECASE),
    re.compile(r"^notification-importantget instant alerts", re.IGNORECASE),
    re.compile(r"^yes, keep me updated$", re.IGNORECASE),
    re.compile(r"^audio-(rewind|play|forward)$", re.IGNORECASE),
    re.compile(r"^your browser does not support the audio element\.?$", re.IGNORECASE),
    re.compile(r"^follow ap.?s coverage\b", re.IGNORECASE),
    re.compile(r"^follow the associated press for full coverage\b", re.IGNORECASE),
    re.compile(r"^use precise geolocation data\b", re.IGNORECASE),
    re.compile(r"^actively scan device characteristics\b", re.IGNORECASE),
    re.compile(r"^with your acceptance\b", re.IGNORECASE),
    re.compile(r"^\*\s*(copy|print|share|save)\s*$", re.IGNORECASE),
    re.compile(r"^[-•]\s*(copy|print|share|save)\s*$", re.IGNORECASE),
    re.compile(r"^followfollow", re.IGNORECASE),
    re.compile(r"^you are now following", re.IGNORECASE),
    re.compile(r"^updates from your news topics", re.IGNORECASE),
    re.compile(r"^by \[[^\]]+\]\(https?://[^)]+\)(,\s*\[[^\]]+\]\(https?://[^)]+\))*", re.IGNORECASE),
    re.compile(r".*\(AP Photo/[^)]+\)\s*$", re.IGNORECASE),
    re.compile(r"^\d+\s+of\s+\d+(\s*\|)?$", re.IGNORECASE),
    re.compile(r"^\[[^\]]+\]\(https?://[^)]+\)$"),
    re.compile(r"^!\[[\s\S]*\]\(https?://[^)]+\)$"),
    re.compile(r"^\*\s*\[[^\]]+\]\(https?://[^)]+\)$"),
    re.compile(r"^\[[^\]]*\]\(https?://[^)]+\)$"),
]

_TERMINAL_NOISE_SECTION_PATTERNS = [
    re.compile(r"^#+\s*related topics$", re.IGNORECASE),
    re.compile(r"^#+\s*more on this story$", re.IGNORECASE),
    re.compile(r"^#+\s*always standing for press freedom\.?$", re.IGNORECASE),
]


def clean_article_text(text: str) -> str:
    """清理 Crawl4AI 返回的 markdown / 文本，保留正文段落并压掉常见站点噪声。"""

    if not text:
        return ""

    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    cleaned: list[str] = []
    skipping_recommendations = False
    previous_normalized = ""
    seen_media_captions: set[str] = set()

    for line in lines:
        if not line:
            if cleaned and cleaned[-1]:
                cleaned.append("")
            continue

        line = _strip_markdown_links(line)
        lowered = line.lower().strip()
        # 只对明确的页脚推荐区截断；cookie、音频控件等只逐行删除，避免误伤后续正文。
        if _starts_terminal_noise_section(line):
            break
        if lowered.startswith("## recommended stories") or lowered == "recommended stories":
            skipping_recommendations = True
            continue
        if skipping_recommendations:
            if line.startswith("* ") or line.startswith("- ") or re.match(r"^\[[^\]]+\]\(https?://", line):
                continue
            skipping_recommendations = False

        if _is_noise_line(line):
            continue
        caption_key = _media_caption_key(line)
        if caption_key and caption_key in seen_media_captions:
            continue
        if caption_key:
            seen_media_captions.add(caption_key)
        normalized = re.sub(r"^#+\s*", "", line).strip()
        normalized = re.sub(r"^[*•-]\s*", "", normalized).strip()
        if normalized.lower() == previous_normalized.lower():
            continue

        cleaned.append(line)
        previous_normalized = normalized

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


def _starts_terminal_noise_section(line: str) -> bool:
    return any(pattern.search(line.strip()) for pattern in _TERMINAL_NOISE_SECTION_PATTERNS)


def _media_caption_key(line: str) -> str | None:
    """对 AP 图片/视频说明做温和去重：保留首次出现，只删除后续重复说明。"""

    lowered = line.lower()
    if not re.search(r"\b(pool via ap|via ap|ap photo)\b", lowered):
        return None
    normalized = re.sub(r"\\", "", lowered)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if len(normalized) < 80:
        return None
    return normalized


def _compact_blank_lines(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text)
    return re.sub(r"[ \t]+", " ", text)


def _strip_markdown_links(line: str) -> str:
    line = re.sub(r"!\[([^\]]*)\]\(https?://[^)]+\)", r"\1", line)
    return re.sub(r"\[([^\]]+)\]\(https?://[^)]+\)", r"\1", line)


def _truncate_at_sentence(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    window = text[:limit]
    sentence_end = max(window.rfind(". "), window.rfind("。"), window.rfind("! "), window.rfind("? "))
    if sentence_end >= 160:
        return window[: sentence_end + 1].strip()
    return window.rstrip() + "..."
