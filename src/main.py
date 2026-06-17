"""程序入口：加载配置，启动调度服务、托盘与右下角小面板。

架构：
  - 主线程运行 Tkinter 小面板的事件循环(GUI 必须在主线程)
  - 系统托盘在后台线程运行
  - 调度器在后台线程触发提醒
  - 托盘/调度器通过命令队列与主线程的小面板通信(线程安全)

运行: python -m src.main
"""
from __future__ import annotations

import logging
import queue
import sys

from .config import load_config
from .panel import MiniPanel
from .reminder import AppService
from .tray import Tray
from .web.server import run_in_thread


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> int:
    setup_logging()
    log = logging.getLogger("water")

    cfg = load_config()
    service = AppService(cfg)

    # 命令队列：后台线程 -> 主线程小面板
    cmd_q: queue.Queue[str] = queue.Queue()
    service.on_reminder = lambda: cmd_q.put("reminder")
    service.on_progress_changed = lambda: cmd_q.put("refresh")

    try:
        service.start()
    except Exception as exc:  # noqa: BLE001
        log.error("启动失败: %s", exc)
        return 1

    run_in_thread(service, cfg)

    panel = MiniPanel(service, cmd_q)
    tray = Tray(
        service,
        on_activate=lambda: cmd_q.put("toggle"),
        on_quit=lambda: cmd_q.put("quit"),
    )
    tray.start_detached()

    log.info("喝水提醒已启动：点击托盘图标可打开右下角小面板。")
    try:
        panel.run()  # 阻塞，直到面板收到 quit 销毁
    except KeyboardInterrupt:
        pass
    finally:
        tray.stop()
        service.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
