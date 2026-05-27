# 这个文件提供最小正文抽取工具，把网页 HTML 转成后续可判断和存储的纯文本。
from __future__ import annotations

import re


def strip_html(html: str) -> str:
    """极简正文抽取：去掉脚本、样式和 HTML 标签。

    第一版先够测试和简单页面用，复杂正文抽取后续可替换成专业库。
    """

    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_title(html: str) -> str | None:
    """从 HTML title 标签里取页面标题。"""

    match = re.search(r"(?is)<title>(.*?)</title>", html)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1)).strip()
