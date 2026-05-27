# 这个测试文件验证网页正文清洗逻辑，确保导航、分享、广告和推荐阅读不会混进后续新闻摘要。
from module1.news.text_cleaner import clean_article_text, first_meaningful_excerpt


def test_clean_article_text_removes_common_page_noise():
    raw_text = """
Share
Copy
Link copied
[Home](https://www.example.com)
Advertisement

US officials said the latest round of tensions prompted emergency calls between regional partners, while diplomats urged both sides to avoid further escalation.

Read More
## Recommended stories
* [Another story](https://www.example.com/another)

The second paragraph adds context from officials and witnesses, without relying on page navigation or recommendation modules.
"""

    cleaned = clean_article_text(raw_text)

    assert "Share" not in cleaned
    assert "Advertisement" not in cleaned
    assert "Another story" not in cleaned
    assert "US officials said" in cleaned
    assert "The second paragraph adds context" in cleaned


def test_first_meaningful_excerpt_prefers_article_paragraph():
    raw_text = """
Print
Save

US officials said the latest round of tensions prompted emergency calls between regional partners, while diplomats urged both sides to avoid further escalation.

The second paragraph adds context from officials and witnesses, without relying on page navigation or recommendation modules.
"""

    excerpt = first_meaningful_excerpt(raw_text, limit=180)

    assert excerpt.startswith("US officials said")
    assert "Print" not in excerpt
    assert "Save" not in excerpt
