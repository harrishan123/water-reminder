"""运行路径解析：兼容源码运行与 PyInstaller 打包(.exe)两种形态。

打包后有两类路径需要区分：
  - 内置只读资源(网页文件、图标)：随 exe 一起打包，位于解压目录 sys._MEIPASS
  - 可写数据(config.yaml、data/)：必须放在 exe 旁边才能持久保存、方便用户编辑

源码运行时两者都相对项目根目录(本文件位于 src/ 下)。
"""
from __future__ import annotations

import os
import sys

_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SRC_DIR)


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包后的可执行文件中。"""
    return bool(getattr(sys, "frozen", False))


def resource_path(*parts: str) -> str:
    """内置只读资源路径(网页、图标等)。打包后取自解压目录，保持与源码相同的相对结构。"""
    base = getattr(sys, "_MEIPASS", _PROJECT_ROOT) if is_frozen() else _PROJECT_ROOT
    return os.path.join(base, *parts)


def data_path(*parts: str) -> str:
    """可写数据路径(config.yaml、data/)。打包后位于 exe 同级目录，源码运行时为项目根。"""
    base = os.path.dirname(sys.executable) if is_frozen() else _PROJECT_ROOT
    return os.path.join(base, *parts)
