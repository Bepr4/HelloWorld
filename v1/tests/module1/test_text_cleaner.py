# 这个测试文件验证网页正文清洗逻辑，确保导航、分享、广告和推荐阅读不会混进后续新闻摘要。
from module1.news.text_cleaner import clean_article_text, first_meaningful_excerpt


def test_clean_article_text_removes_common_page_noise():
    raw_text = """
Share
Copy
* Copy
* Print
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
    assert "* Copy" not in cleaned
    assert "* Print" not in cleaned
    assert "Another story" not in cleaned
    assert "US officials said" in cleaned
    assert "The second paragraph adds context" in cleaned


def test_clean_article_text_deduplicates_headings_and_strips_links():
    raw_text = """
# Trump offers mixed messages about path ahead for US war against Iran
## Trump offers mixed messages about path ahead for US war against Iran
Trump offers mixed messages about path ahead for US war against Iran

The United States said it forcibly seized an Iranian-flagged cargo ship near the Strait of Hormuz, according to [officials](https://example.com/officials), while diplomats urged restraint.
* Copy
* Print
"""

    cleaned = clean_article_text(raw_text)

    assert cleaned.count("Trump offers mixed messages about path ahead for US war against Iran") == 1
    assert "[officials]" not in cleaned
    assert "according to officials" in cleaned


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


def test_clean_article_text_removes_ap_social_and_footer_noise():
    raw_text = """
World News
Sign in with Google. Opens in new tab
* LinkedIn
Leer en español
Comments

Russian officials said negotiations would continue after a week of long-range strikes, while Ukrainian officials pushed allies for additional air defense systems.

The report added battlefield context from military analysts and diplomats, keeping the focus on the current state of the conflict rather than site controls.

Follow AP’s coverage of the war at https://apnews.com/hub/russia-ukraine
## Always standing for press freedom.
Defend press freedom
"""

    cleaned = clean_article_text(raw_text)

    assert "Russian officials said negotiations" in cleaned
    assert "battlefield context" in cleaned
    assert "World News" not in cleaned
    assert "Sign in with Google" not in cleaned
    assert "LinkedIn" not in cleaned
    assert "Leer en español" not in cleaned
    assert "Comments" not in cleaned
    assert "Follow AP" not in cleaned
    assert "Defend press freedom" not in cleaned


def test_clean_article_text_removes_bbc_related_footer():
    raw_text = """
Ukraine's latest request for air defense systems came as European leaders discussed a new sanctions package and pledged to keep weapons deliveries flowing.

Officials in Kyiv said the timing mattered because civilian infrastructure had again been hit overnight in several regions near the front line.

## Related topics
Russia-Ukraine war
Europe
## More on this story
How Ukraine is defending its cities
"""

    cleaned = clean_article_text(raw_text)

    assert "Ukraine's latest request" in cleaned
    assert "Officials in Kyiv" in cleaned
    assert "Related topics" not in cleaned
    assert "Russia-Ukraine war" not in cleaned
    assert "More on this story" not in cleaned
    assert "How Ukraine is defending" not in cleaned


def test_clean_article_text_removes_iab_consent_footer():
    raw_text = """
The article body describes a new diplomatic push and includes enough context to be useful for downstream summaries and source notes.

A second paragraph explains why the timing of the talks matters, citing officials and recent battlefield developments.

List of IAB Vendors
Use precise geolocation data
Actively scan device characteristics for identification
Consent Leg.Interest
I Reject All
Confirm My Choices
"""

    cleaned = clean_article_text(raw_text)

    assert "The article body describes" in cleaned
    assert "A second paragraph explains" in cleaned
    assert "List of IAB Vendors" not in cleaned
    assert "Use precise geolocation data" not in cleaned
    assert "Actively scan device characteristics" not in cleaned
    assert "I Reject All" not in cleaned
    assert "Confirm My Choices" not in cleaned


def test_clean_article_text_removes_live_ui_without_cutting_body_sections():
    raw_text = """
# US inserts itself into Israel's war with Iran
Follow AP’s live updates on the Israel-Iran war.
TEL AVIV, Israel (AP) — The United States struck three sites in Iran early Sunday, inserting itself into Israel's war.

## Rising gasoline prices are a double blow for drivers who use their own vehicles for work
Millions of people have jobs that require using personal vehicles for work, like delivery drivers and ride-share providers.
▶ _Read more_

## Starmer urges a joint response by government and industry to Iran war fallout
British Prime Minister Keir Starmer's comments came after meeting Monday with the leaders of energy, shipping and banking firms.
"""

    cleaned = clean_article_text(raw_text)

    assert "Follow AP’s live updates" not in cleaned
    assert "Read more" not in cleaned
    assert "TEL AVIV" in cleaned
    assert "Rising gasoline prices" in cleaned
    assert "Millions of people have jobs" in cleaned
    assert "Starmer urges" in cleaned
    assert "energy, shipping and banking firms" in cleaned


def test_clean_article_text_removes_embedded_cookie_and_audio_controls_without_cutting_body():
    raw_text = """
In eastern Tehran, a resident keeps the front door of his apartment unlocked so the family can reach an underground car park during explosions.

#### This content is unavailable due to your cookie settings.
To continue, please allow functional cookies from third-party platforms.
AllowManage cookie preferences

The current conflict bears little resemblance to last year's contained warfare and has widened across the region.

Your browser does not support the audio element.
audio-rewind
audio-play
audio-forward
ListenListen (7 mins)
notification-importantGet instant alerts and updates based on your interests. Be the first to know when big stories happen.
Yes, keep me updated

The financial burden of this limitless war is staggering, and analysts are watching energy and shipping costs.
"""

    cleaned = clean_article_text(raw_text)

    assert "front door of his apartment" in cleaned
    assert "current conflict bears little resemblance" in cleaned
    assert "financial burden" in cleaned
    assert "cookie settings" not in cleaned
    assert "AllowManage" not in cleaned
    assert "audio-rewind" not in cleaned
    assert "ListenListen" not in cleaned
    assert "instant alerts" not in cleaned
    assert "keep me updated" not in cleaned


def test_clean_article_text_deduplicates_repeated_ap_media_captions_but_keeps_one():
    caption_plain = (
        "President Donald Trump speaks from the East Room of the White House in Washington, Saturday, June 21, 2025, "
        "after the U.S. military struck three Iranian nuclear and military sites. (Carlos Barria/Pool via AP)"
    )
    caption_escaped = (
        "President Donald Trump speaks from the East Room of the White House in Washington, Saturday, June 21, 2025, "
        "after the U.S. military struck three Iranian nuclear and military sites. \\(Carlos Barria/Pool via AP\\)"
    )
    raw_text = f"""
# US strikes Iranian nuclear sites
{caption_plain}
{caption_escaped}
{caption_plain}

The attack marked a major escalation in the war and prompted warnings from regional governments.
"""

    cleaned = clean_article_text(raw_text)

    assert cleaned.count("President Donald Trump speaks from the East Room") == 1
    assert "The attack marked a major escalation" in cleaned
