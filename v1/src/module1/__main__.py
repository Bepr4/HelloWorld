# 这个文件让模块一可以通过 python -m module1 直接启动命令行采集。
from module1.cli import main


if __name__ == "__main__":
    main()
