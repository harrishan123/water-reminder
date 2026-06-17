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

APP_NAME = "WaterReminder"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _run_command() -> str:
    """返回开机要执行的命令。优先用 pythonw(无控制台窗口)。"""
    pyw = sys.executable
    # 尝试用同目录下的 pythonw.exe，避免弹出黑窗
    candidate = os.path.join(os.path.dirname(pyw), "pythonw.exe")
    if os.path.exists(candidate):
        pyw = candidate
    return f'"{pyw}" -m src.main'


def enable() -> None:
    import winreg

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # 用 cmd 切到项目目录再启动，确保相对路径(config/data)正确
    cmd = f'cmd /c "cd /d "{root}" && {_run_command()}"'
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
