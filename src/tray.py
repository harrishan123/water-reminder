"""系统托盘图标与右键菜单。

托盘在后台线程运行(主线程留给 Tkinter 小面板)。点击图标的默认动作
触发 on_activate 回调(打开/收起右下角小面板)。
"""
from __future__ import annotations

import logging
import threading
from typing import Callable

import pystray

from . import __version__
from .icon import drop_image

log = logging.getLogger("water.tray")


class Tray:
    def __init__(self, service, on_activate: Callable[[], None], on_quit: Callable[[], None]):
        self.service = service
        self._on_activate = on_activate
        self._on_quit = on_quit
        self.icon = pystray.Icon("water_reminder", drop_image(64), f"喝水提醒 v{__version__}")
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
            pystray.MenuItem("我起床了", self._on_wake),
            pystray.MenuItem("我上班了", pystray.Menu(
                pystray.MenuItem("上班前：没喝", self._clock_in_action(0)),
                pystray.MenuItem("上班前：200ml", self._clock_in_action(200)),
                pystray.MenuItem("上班前：350ml", self._clock_in_action(350)),
                pystray.MenuItem("上班前：500ml", self._clock_in_action(500)),
            )),
            pystray.MenuItem("我下班了", pystray.Menu(
                pystray.MenuItem("今晚约 22:30 睡", self._clock_out_action("22:30")),
                pystray.MenuItem("今晚约 23:00 睡", self._clock_out_action("23:00")),
                pystray.MenuItem("今晚约 23:30 睡", self._clock_out_action("23:30")),
                pystray.MenuItem("今晚约 00:00 睡", self._clock_out_action("00:00")),
            )),
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
            pystray.MenuItem(
                "开机自启",
                self._on_toggle_autostart,
                checked=lambda item: self._autostart_enabled(),
            ),
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

    def _on_wake(self, icon, item) -> None:
        self.service.wake_up()
        mt = self.service.morning_target()
        self.service.notifier.show_message(
            "早安 ☀️",
            f"上班前这段建议喝约 {mt}ml，先来一杯吧 💧" if mt else "起床先喝一杯水 💧",
        )
        self._refresh()

    def _clock_in_action(self, ml: int):
        def _handler(icon, item) -> None:
            self.service.clock_in(ml)
            self._refresh()
        return _handler

    def _clock_out_action(self, bedtime: str):
        def _handler(icon, item) -> None:
            # 会调 AI，放后台线程，完成后弹通知告知建议
            def _job():
                ws = self.service.clock_out(bedtime)
                aw = (ws or {}).get("after_work") or {}
                self.service.notifier.show_message(
                    "下班后安排",
                    f"还需再喝约 {aw.get('after_ml', 0)}ml\n{aw.get('advice', '')}",
                )
            self._run_bg(_job, "clock-out")
        return _handler

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

    def _autostart_enabled(self) -> bool:
        from . import autostart

        try:
            return autostart.is_enabled()
        except Exception:  # noqa: BLE001
            return False

    def _on_toggle_autostart(self, icon, item) -> None:
        from . import autostart

        try:
            autostart.toggle()
        except Exception as exc:  # noqa: BLE001
            log.warning("切换开机自启失败: %s", exc)
        self._refresh()

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
