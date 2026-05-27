# 这个测试文件验证基准时间线构建器能从中文日期文本里抽取时间点。
from module1.intake.timeline_builder import TimelineBuilder
from module1.intake.wiki_client import StaticWikiClient, WikiPage, WikiSection
from module1.models import EventScopeConfirmation


def test_timeline_builder_extracts_chinese_dates():
    scope = EventScopeConfirmation(
        event_query="2020 年苏莱曼尼事件",
        confirmed_event="2020 年苏莱曼尼事件",
        confirmed_scope="2020 年 1 月苏莱曼尼遇袭及后续美伊冲突",
        user_confirmed=True,
    )
    page = WikiPage(
        title="Fixture",
        url="https://example.org/wiki",
        sections=[
            WikiSection(
                title="Timeline",
                text="2020 年 1 月 3 日，美军发动袭击。2020 年 1 月 8 日，伊朗发动导弹袭击。",
            )
        ],
    )

    timeline = TimelineBuilder(StaticWikiClient({scope.confirmed_event: page})).build_baseline_timeline(scope)

    assert [item.start_date for item in timeline] == ["2020-01-03", "2020-01-08"]
    assert timeline[0].timeline_item_id == "tl_001"
    assert timeline[0].time_type == "point"
