# 这个文件声明新闻子模块的公开入口，外部通过 NewsAgent 调用新闻采集流程。
from module1.news.agent import NewsAgent

__all__ = ["NewsAgent"]
