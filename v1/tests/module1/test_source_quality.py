# 这个测试文件验证新闻来源质量门，确保明显的导航、同意弹窗和主题页污染不会进入材料包。
from module1.news.source_quality import source_quality_issue


def test_source_quality_flags_iab_consent_noise_before_article_length_checks():
    text = """
The report includes enough ordinary words to look article-like at first glance, but the captured body has clearly pulled in a consent management panel.

List of IAB Vendors
Use precise geolocation data
Actively scan device characteristics for identification
Consent Leg.Interest
I Reject All
Confirm My Choices
"""

    issue = source_quality_issue("https://apnews.com/article/example", "Example", text)

    assert issue == "navigation_or_topic_noise"
