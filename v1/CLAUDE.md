# CLAUDE.md

## 环境

- Conda 环境名称：`v1`（Python 3.13）
- 激活命令：`conda activate v1`
- 解释器路径：`C:\Users\li636\.conda\envs\v1\python.exe`
- 已安装依赖：`pydantic`、`pytest`

## 项目结构

```
src/module1/          - 主代码
  llm/                - LLM 调用客户端
  intake/             - 事件接入与时间线生成
  news/               - 新闻采集 Agent
  finance/            - 金融模块占位（尚未实现）
tests/module1/        - 单元测试
configs/module1/      - 配置文件（source_registry.yaml）
```

## 代码规范

- 写代码时必须带中文注释

## 常用命令

- 跑全部测试：`conda run -n v1 pytest tests/ -v`
- 跑单个测试：`conda run -n v1 pytest tests/module1/test_xxx.py -v`
