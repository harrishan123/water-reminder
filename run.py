"""打包入口启动器。

src/main.py 使用包内相对导入(from .config ...)，必须作为 src 包的一部分运行，
不能被 PyInstaller 当作顶层脚本直接执行。这里以正规方式导入并调用。
源码运行仍用 `python -m src.main`，本文件仅供打包。
"""
import sys

from src.main import main

if __name__ == "__main__":
    sys.exit(main())
