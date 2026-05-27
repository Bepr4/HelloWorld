# 这个文件声明 module1 包的公开入口，方便外部直接调用模块一流水线。
"""模块一 v1：事件接入、新闻采集和事件基础信息库落盘。"""

from module1.pipeline import run_module1

__all__ = ["run_module1"]
