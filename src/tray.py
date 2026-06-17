"""系统托盘图标与右键菜单。

托盘在后台线程运行(主线程留给 Tkinter 小面板)。点击图标的默认动作
触发 on_activate 回调(打开/收起右下角小面板)。
"""
from __future__ import annotations

import logging
import threading
from typing import Callable

import pystray

from .icon import drop_image

log = logging.getLogger("water.tray")


class Tray:
    def __init__(self, service, on_activate: Callable[[], None], on_quit: Callable[[], None]):
        self.service = service
        self._on_activate = on_activate
        self._on_quit = on_quit
        self.icon = pystray.Icon("water_reminder", drop_image(64), "喝水提醒")
        self.icon.menu = self._build_menu()
        self._thread: threading.Thread | None = None

    def _build_menu(self) -> pystray.Menu:
        return pystray.Menu(
            # 默认动作(点击图标/双击)：打开小面板，标签同时显示进度
            pystray.MenuItem(
                lambda item: f"喝水提醒 · {self.service.progress_text()}",
                self._activate,
                default=True,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("打开小面板", self._activate),
            pystray.MenuItem("喝一杯", self._on_drink),
            pystray.MenuItem("撤销上一杯", self._on_undo),
            pystray.MenuItem(
                lambda item: "恢复提醒" if self.service.paused else "暂停提醒",
                self._on_toggle_pause,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("打开控制面板(网页)", self._on_open_web),
            pystray.MenuItem("生成今日报告", self._on_daily_report),
            pystray.MenuItem("生成本周报告", self._on_weekly_report),
            pystray.MenuItem("重新计算今日目标", self._on_recompute_goal),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._on_quit_clicked),
        )

    def _refresh(self) -> None:
        try:
            self.icon.update_menu()
        except Exception:  # noqa: BLE001
            pass

    def _run_bg(self, fn: Callable[[], None], name: str) -> None:
        """在后台线程执行可能调用 AI(耗时几十秒)的操作，避免阻塞托盘消息循环。"""

        def _job():
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                log.warning("%s 失败: %s", name, exc)
            finally:
                self._refresh()

        threading.Thread(target=_job, daemon=True, name=name).start()

    # ---------- 菜单回调 ----------
    def _activate(self, icon, item) -> None:
        self._on_activate()

    def _on_drink(self, icon, item) -> None:
        self.service.drink()
        self._refresh()

    def _on_undo(self, icon, item) -> None:
        self.service.undo_last_drink()
        self._refresh()

    def _on_toggle_pause(self, icon, item) -> None:
        self.service.toggle_pause()
        self._refresh()

    def _on_open_web(self, icon, item) -> None:
        from .web.server import open_panel

        open_panel(self.service.cfg)

    def _on_daily_report(self, icon, item) -> None:
        # 手动点击视为"要一份新的"，强制忽略缓存重新生成
        self._run_bg(lambda: self.service.send_daily_report(force=True), "daily-report")

    def _on_weekly_report(self, icon, item) -> None:
        self._run_bg(lambda: self.service.send_weekly_report(force=True), "weekly-report")

    def _on_recompute_goal(self, icon, item) -> None:
        self._run_bg(self.service.recompute_goal, "recompute-goal")

    def _on_quit_clicked(self, icon, item) -> None:
        icon.stop()
        self._on_quit()

    # ---------- 运行 ----------
    def start_detached(self) -> None:
        """在后台线程运行托盘(Windows 支持非主线程消息循环)。"""
        self._thread = threading.Thread(target=self.icon.run, daemon=True, name="tray")
        self._thread.start()

    def stop(self) -> None:
        try:
            self.icon.stop()
        except Exception:  # noqa: BLE001
            pass
