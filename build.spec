# PyInstaller 打包配置。构建命令：
#   pyinstaller build.spec
# 产物在 dist/喝水提醒/ 文件夹，内含 喝水提醒.exe，可整体压缩分发。
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []

# 这些库通过动态导入加载子模块，用 collect_all 一并收集，避免打包后缺失
for pkg in ("win11toast", "winsdk", "apscheduler", "pystray"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# 内置只读资源：网页文件与图标，保持与源码相同的相对路径
datas += [
    ("src/web/static", "src/web/static"),
    ("assets/icon.ico", "assets"),
]

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # 排除环境里装着但本程序用不到的重型库，避免 PyInstaller 扫描时崩溃/产物臃肿
    excludes=[
        "torch", "torchvision", "torchaudio", "tensorflow",
        "cv2", "matplotlib", "pandas", "scipy", "numpy",
        "IPython", "notebook", "sklearn",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="喝水提醒",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,            # 无控制台黑窗(GUI 程序)
    icon="assets/icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="喝水提醒",
)
