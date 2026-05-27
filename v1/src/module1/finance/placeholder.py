# 这个文件提供金融 Agent 的 v1 占位逻辑，先保留结构字段，不做真实市场分析。
from __future__ import annotations

from module1.models import TimelineCollectionTask


def run_finance_placeholder(task: TimelineCollectionTask) -> dict:
    """金融 Agent 第一版占位。

    先保留事件基础信息库里的金融字段，但不接真实市场数据、不做价格分析。
    """

    return {
        "financial_evidence": [],
        "market_trend_spans": [],
        "status": "not_implemented",
    }
