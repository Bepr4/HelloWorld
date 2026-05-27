# AGENT.md

## 环境

- Conda 环境名称：`v1`（Python 3.13）
- 解释器路径：`C:\Users\li636\.conda\envs\v1\python.exe`
- 已安装依赖：`pydantic`、`pytest`

## 规则

1. 运行任何 Python 脚本或测试前，确保使用 `v1` 环境。
2. 在新终端或后台任务中执行命令时，用 `conda run -n v1 <命令>`。
3. 新增依赖时，安装到 `v1` 环境：`conda run -n v1 pip install <包名>`。
4. 写代码时必须带中文注释。
