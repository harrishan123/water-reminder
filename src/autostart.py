"""开机自启管理(Windows)。

通过写入注册表 HKCU\\...\\Run 实现登录时自动运行。
用法:
  python -m src.autostart enable
  python -m src.autostart disable
  python -m src.autostart status
"""
from __future__ import annotations

import os
import sys

from .paths import is_frozen

APP_NAME = "WaterReminder"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _registry_command() -> str:
    """返回写入注册表 Run 键的开机启动命令。

    打包态(exe)：直接运行 exe 自身(它按 exe 同级目录读写 config/data)。
    源码态：用 pythonw 无黑窗启动，并先切到项目目录保证相对路径正确。
    """
    if is_frozen():
        return f'"{sys.executable}"'
    pyw = sys.executable
    candidate = os.path.join(os.path.dirname(pyw), "pythonw.exe")
    if os.path.exists(candidate):
        pyw = candidate
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return f'cmd /c "cd /d "{root}" && "{pyw}" -m src.main"'


def is_enabled() -> bool:
    """当前是否已设置开机自启。"""
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, APP_NAME)
        return True
    except FileNotFoundError:
        return False


def toggle() -> bool:
    """切换开机自启，返回切换后的状态(True=已启用)。"""
    if is_enabled():
        disable()
        return False
    enable()
    return True


def enable() -> None:
    import winreg

    cmd = _registry_command()
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
    print(f"已启用开机自启: {cmd}")


def disable() -> None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, APP_NAME)
        print("已取消开机自启")
    except FileNotFoundError:
        print("当前未设置开机自启")


def status() -> None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
        print(f"已启用: {value}")
    except FileNotFoundError:
        print("未启用开机自启")


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    if action == "enable":
        enable()
    elif action == "disable":
        disable()
    else:
        status()
    return 0


if __name__ == "__main__":
    sys.exit(main())
