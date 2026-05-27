# 这个文件提供模块一命令行入口，方便直接运行真实新闻采集并查看落盘位置。
from __future__ import annotations

import argparse

from module1.pipeline import run_module1
from module1.settings import load_module1_settings


def main() -> None:
    """从命令行接收事件输入，运行模块一采集流水线。"""

    parser = argparse.ArgumentParser(description="Run module1 real news collection")
    parser.add_argument("event_query", help="用户输入的事件，例如 Iran conflict")
    args = parser.parse_args()

    settings = load_module1_settings()
    package = run_module1(args.event_query, settings=settings)

    event_dir = settings.storage_root / "events" / package.event_id
    print(f"event_id={package.event_id}")
    print(f"source_documents={len(package.source_documents)}")
    print(f"news_blocks={len(package.news_blocks)}")
    print(f"timeline_update_suggestions={len(package.timeline_update_suggestions)}")
    print(f"output_dir={event_dir}")


if __name__ == "__main__":
    main()
