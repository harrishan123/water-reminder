"""生成无终端启动器与桌面快捷方式。

用法:
  python -m src.shortcut            # 生成启动器 + 桌面快捷方式

生成后：双击桌面的「喝水提醒」图标即可启动(无黑窗)。
"""
from __future__ import annotations

import os
import subprocess
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VBS_PATH = os.path.join(ROOT_DIR, "启动.vbs")
ICON_PATH = os.path.join(ROOT_DIR, "assets", "icon.ico")
SHORTCUT_NAME = "喝水提醒.lnk"


def _pythonw() -> str:
    """返回 pythonw.exe 路径(无控制台窗口)；找不到则退回 python.exe。"""
    cand = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return cand if os.path.exists(cand) else sys.executable


def make_icon() -> str:
    """画一个水滴图标并保存为 .ico(多尺寸)。"""
    from .icon import drop_image

    os.makedirs(os.path.dirname(ICON_PATH), exist_ok=True)
    img = drop_image(256)
    img.save(ICON_PATH, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return ICON_PATH


def make_vbs() -> str:
    """生成静默启动脚本(切到项目目录并用 pythonw 启动，无黑窗)。"""
    pyw = _pythonw()
    content = (
        'Set sh = CreateObject("WScript.Shell")\r\n'
        f'sh.CurrentDirectory = "{ROOT_DIR}"\r\n'
        f'sh.Run """{pyw}"" -m src.main", 0, False\r\n'
    )
    # 用系统本地编码(GBK)且不带 BOM，避免 wscript 报"无效字符"
    with open(VBS_PATH, "w", encoding="mbcs", newline="") as fh:
        fh.write(content)
    return VBS_PATH


def make_desktop_shortcut() -> str:
    """在桌面创建指向启动器的快捷方式(带图标，无热键)。"""
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    lnk_path = os.path.join(desktop, SHORTCUT_NAME)
    # 通过 PowerShell 的 WScript.Shell COM 创建 .lnk
    ps = f"""
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut('{lnk_path}')
$lnk.TargetPath = '{VBS_PATH}'
$lnk.WorkingDirectory = '{ROOT_DIR}'
$lnk.IconLocation = '{ICON_PATH}'
$lnk.HotKey = ''
$lnk.Description = '喝水提醒'
$lnk.Save()
"""
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        check=True,
        capture_output=True,
        text=True,
    )
    return lnk_path


def main() -> int:
    icon = make_icon()
    vbs = make_vbs()
    lnk = make_desktop_shortcut()
    print("已生成启动器:", vbs)
    print("已生成图标:", icon)
    print("已创建桌面快捷方式:", lnk)
    print("现在可以双击桌面「喝水提醒」图标启动(无终端窗口)。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
