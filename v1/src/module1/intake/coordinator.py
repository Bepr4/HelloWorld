# 这个文件实现统筹 Agent 的核心流程：确认事件范围，并生成新闻采集任务单。
from __future__ import annotations

from uuid import uuid4

from module1.models import EventScopeConfirmation, TimelineCollectionTask, TimelineItem


class ScopeNotConfirmedError(RuntimeError):
    """用户还没有确认事件范围时阻止后续采集。"""

    pass


class Coordinator:
    """事件接入与任务分发 Agent 的第一版代码骨架。

    现在先做半自动确认和任务单生成，复杂多轮对话后续再接。
    """

    def confirm_scope(
        self,
        event_query: str,
        *,
        confirmed_event: str | None = None,
        confirmed_scope: str | None = None,
        time_range: str | None = None,
        locations: list[str] | None = None,
        key_actors: list[str] | None = None,
        exclude_scope: str | None = None,
        background_rule: str | None = None,
        user_confirmed: bool = True,
    ) -> EventScopeConfirmation:
        """生成事件范围确认对象。

        真实产品里这里会接用户确认卡；第一版可以由调用方直接传入确认后的范围。
        """

        normalized_query = " ".join(event_query.split())
        return EventScopeConfirmation(
            event_query=event_query,
            confirmed_event=confirmed_event or normalized_query,
            confirmed_scope=confirmed_scope or normalized_query,
            time_range=time_range,
            locations=locations or [],
            key_actors=key_actors or [],
            exclude_scope=exclude_scope,
            background_rule=background_rule,
            user_confirmed=user_confirmed,
        )

    def build_timeline_collection_task(
        self,
        scope: EventScopeConfirmation,
        baseline_timeline: list[TimelineItem],
        *,
        event_id: str | None = None,
    ) -> TimelineCollectionTask:
        """把已确认事件范围和基准时间线转成内部采集任务单。"""

        if not scope.user_confirmed:
            raise ScopeNotConfirmedError("User must confirm event scope before collection starts")

        # event_id 用短 UUID，避免同一个事件多次运行时互相覆盖。
        resolved_event_id = event_id or f"event_{uuid4().hex[:12]}"
        return TimelineCollectionTask(
            event_id=resolved_event_id,
            event_query=scope.event_query,
            confirmed_event=scope.confirmed_event,
            confirmed_scope=scope.confirmed_scope,
            baseline_timeline=baseline_timeline,
            exclude_scope=scope.exclude_scope,
            news_task=(
                "Collect P0-P3 source materials with Timeline Pass and Discovery Pass. "
                "Return source_documents, news_blocks, and timeline_update_suggestions."
            ),
            finance_task="not_implemented",
        )
