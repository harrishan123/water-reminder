"""右下角悬浮小面板(Tkinter)。

两种展示模式：
  - normal: 点击托盘图标手动打开，展示进度仪表盘
  - reminder: 到了提醒时间自动弹出，向用户提问"刚才喝水了吗？"，
              提供几个常用毫升数选项 +「还没喝」按钮。
              未做选择就关闭(点外面、按 ✕、丢失焦点) -> 视为没喝。

线程模型：托盘/调度器在后台线程，通过命令队列驱动主线程的 Tk 循环。
支持的命令：toggle / show / hide / reminder / refresh / quit
"""
from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from tkinter import simpledialog

log = logging.getLogger("water.panel")

BG = "#ffffff"
BORDER = "#d8e3f0"
BLUE = "#1e90ff"
BLUE_DARK = "#1573d6"
OK = "#2bb673"
WARN = "#f0a040"
TEXT = "#1f2d3d"
MUTED = "#7a8aa0"
TRACK = "#e6edf6"
GHOST = "#eef3fb"

FONT = "Microsoft YaHei UI"


class MiniPanel:
    def __init__(self, service, cmd_queue: queue.Queue):
        self.service = service
        self.q = cmd_queue
        self.width = 300
        self.height = 430
        self.visible = False
        self.mode = "normal"  # "normal" | "reminder"
        self._responded = False  # reminder 模式下是否已选择

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("喝水提醒")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-alpha", 0.98)
        except tk.TclError:
            pass

        self._build()
        self.root.bind("<FocusOut>", self._on_focus_out)
        self._poll()

    # ---------- 构建界面 ----------
    def _build(self) -> None:
        outer = tk.Frame(self.root, bg=BORDER)
        outer.pack(fill="both", expand=True)
        self.card = tk.Frame(outer, bg=BG)
        self.card.pack(fill="both", expand=True, padx=1, pady=1)

        # 标题栏
        top = tk.Frame(self.card, bg=BG)
        top.pack(fill="x", padx=16, pady=(14, 4))
        self.title_lbl = tk.Label(
            top, text="💧 喝水提醒", bg=BG, fg=TEXT, font=(FONT, 13, "bold")
        )
        self.title_lbl.pack(side="left")
        close = tk.Label(top, text="✕", bg=BG, fg=MUTED, font=(FONT, 12), cursor="hand2")
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self.hide())

        # 仅 reminder 模式显示的提醒文案
        self.subtitle_lbl = tk.Label(
            self.card, text="", bg=BG, fg=MUTED, font=(FONT, 9), wraplength=270, justify="center"
        )

        # 进度环
        self.canvas = tk.Canvas(self.card, width=170, height=170, bg=BG, highlightthickness=0)
        self.canvas.pack(pady=(2, 2))

        # 统计行
        self.stat_lbl = tk.Label(self.card, text="", bg=BG, fg=MUTED, font=(FONT, 10))
        self.stat_lbl.pack()

        # 撤销上一杯(误点补救)
        self.undo_lbl = tk.Label(
            self.card, text="↩ 撤销上一杯", bg=BG, fg=MUTED, font=(FONT, 9), cursor="hand2"
        )
        self.undo_lbl.pack(pady=(2, 0))
        self.undo_lbl.bind("<Button-1>", lambda e: self._on_undo())

        # 起床/上/下班打卡
        work_row = tk.Frame(self.card, bg=BG)
        work_row.pack(pady=(4, 0))
        wake = tk.Label(work_row, text="☀️ 起床", bg=BG, fg=BLUE_DARK,
                        font=(FONT, 9), cursor="hand2")
        wake.pack(side="left", padx=8)
        wake.bind("<Button-1>", self._on_wake)
        clock_in = tk.Label(work_row, text="🕘 上班", bg=BG, fg=BLUE_DARK,
                            font=(FONT, 9), cursor="hand2")
        clock_in.pack(side="left", padx=8)
        clock_in.bind("<Button-1>", self._on_clock_in)
        clock_out = tk.Label(work_row, text="🌙 下班", bg=BG, fg=BLUE_DARK,
                             font=(FONT, 9), cursor="hand2")
        clock_out.pack(side="left", padx=8)
        clock_out.bind("<Button-1>", self._on_clock_out)

        # 快捷毫升按钮行
        self.quick_row = tk.Frame(self.card, bg=BG)
        self.quick_row.pack(fill="x", padx=16, pady=(10, 4))

        # 主"喝一杯"按钮
        self.drink_btn = tk.Button(
            self.card, text="喝一杯", command=self._on_drink_default,
            bg=BLUE, fg="white", activebackground=BLUE_DARK, activeforeground="white",
            font=(FONT, 12, "bold"), relief="flat", cursor="hand2", bd=0,
            padx=10, pady=8,
        )
        self.drink_btn.pack(fill="x", padx=16, pady=(4, 4))

        # 次要按钮行(暂停/没喝 + 控制面板)
        row = tk.Frame(self.card, bg=BG)
        row.pack(fill="x", padx=16, pady=(0, 6))
        self.left_btn = tk.Button(
            row, text="暂停提醒", command=self._on_left_action,
            bg=GHOST, fg=BLUE_DARK, activebackground="#e0eafa", font=(FONT, 10),
            relief="flat", cursor="hand2", bd=0, padx=8, pady=6,
        )
        self.left_btn.pack(side="left", expand=True, fill="x", padx=(0, 5))
        tk.Button(
            row, text="控制面板", command=self._on_open_web,
            bg=GHOST, fg=BLUE_DARK, activebackground="#e0eafa", font=(FONT, 10),
            relief="flat", cursor="hand2", bd=0, padx=8, pady=6,
        ).pack(side="left", expand=True, fill="x", padx=(5, 0))

        # 近 7 天迷你柱状
        self.bars = tk.Canvas(self.card, width=268, height=70, bg=BG, highlightthickness=0)
        self.bars.pack(pady=(8, 14))

    def _build_quick_buttons(self, amounts: list[int]) -> None:
        for child in self.quick_row.winfo_children():
            child.destroy()
        for amt in amounts:
            btn = tk.Button(
                self.quick_row, text=f"{amt}ml",
                command=lambda v=amt: self._on_drink(v),
                bg=GHOST, fg=BLUE_DARK, activebackground="#dfe9fb",
                font=(FONT, 10, "bold"), relief="flat", cursor="hand2", bd=0,
                padx=4, pady=6,
            )
            btn.pack(side="left", expand=True, fill="x", padx=2)

    # ---------- 绘制 ----------
    def _draw_ring(self, pct: int, total: int, goal: int) -> None:
        c = self.canvas
        c.delete("all")
        cx, cy, r, w = 85, 85, 64, 16
        color = OK if pct >= 100 else BLUE
        c.create_oval(cx - r, cy - r, cx + r, cy + r, outline=TRACK, width=w)
        if pct > 0:
            extent = -min(pct, 100) * 3.6
            c.create_arc(cx - r, cy - r, cx + r, cy + r, start=90, extent=extent,
                         style="arc", outline=color, width=w)
        c.create_text(cx, cy - 8, text=f"{pct}%", fill=BLUE_DARK, font=(FONT, 24, "bold"))
        c.create_text(cx, cy + 18, text=f"{total} / {goal} ml", fill=MUTED, font=(FONT, 10))

    def _draw_bars(self, week: list) -> None:
        b = self.bars
        b.delete("all")
        if not week:
            return
        max_v = max(max(d["total"], d["goal"]) for d in week) or 1
        n = len(week)
        slot = 268 / n
        bw = 22
        base_y = 52
        for i, d in enumerate(week):
            h = int(d["total"] / max_v * 42)
            x = i * slot + (slot - bw) / 2
            color = OK if d["achieved"] else BLUE
            b.create_rectangle(x, base_y - h, x + bw, base_y, fill=color, outline="")
            b.create_text(x + bw / 2, base_y + 10, text=d["day"][5:].replace("-", "/"),
                          fill=MUTED, font=(FONT, 7))

    def refresh(self) -> None:
        try:
            s = self.service.status()
        except Exception as exc:  # noqa: BLE001
            log.warning("刷新面板失败: %s", exc)
            return
        self._draw_ring(s["pct"], s["total"], s["goal"])
        self.stat_lbl.config(
            text=f"已喝 {s['count']} 杯 · 连续达标 {s['streak']} 天"
        )
        self.drink_btn.config(text=f"喝一杯 ({s['cup_ml']}ml)")
        amounts = self._read_quick_amounts()
        self._build_quick_buttons(amounts)
        self._draw_bars(s["week"])
        self._apply_mode(s)

    def _read_quick_amounts(self) -> list[int]:
        raw = self.service.cfg.get("reminder.quick_amounts", [100, 150, 200, 250]) or []
        out: list[int] = []
        for v in raw:
            try:
                n = int(v)
            except (TypeError, ValueError):
                continue
            if 10 <= n <= 2000:
                out.append(n)
        return out[:4] or [100, 150, 200, 250]

    def _apply_mode(self, status: dict) -> None:
        if self.mode == "reminder":
            self.title_lbl.config(text="💧 刚才喝水了吗？", fg=BLUE_DARK)
            sub = getattr(self.service, "last_reminder_text", "") or "记得补水哦"
            self.subtitle_lbl.config(text=sub, fg=WARN)
            if not self.subtitle_lbl.winfo_ismapped():
                self.subtitle_lbl.pack(after=self.title_lbl.master, padx=16, pady=(0, 4))
            self.left_btn.config(text="还没喝", fg="#a04040")
        else:
            self.title_lbl.config(text="💧 喝水提醒", fg=TEXT)
            if self.subtitle_lbl.winfo_ismapped():
                self.subtitle_lbl.pack_forget()
            self.left_btn.config(
                text="恢复提醒" if status["paused"] else "暂停提醒",
                fg=BLUE_DARK,
            )

    # ---------- 显隐 ----------
    def _place(self) -> None:
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = sw - self.width - 16
        y = sh - self.height - 56
        self.root.geometry(f"{self.width}x{self.height}+{x}+{y}")

    def show(self, mode: str = "normal") -> None:
        self.mode = mode
        self._responded = False
        self.refresh()
        self._place()
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.focus_force()
        self.visible = True

    def hide(self) -> None:
        if not self.visible:
            return
        ignored = self.mode == "reminder" and not self._responded
        self.root.withdraw()
        self.visible = False
        self.mode = "normal"
        if ignored and hasattr(self.service, "report_ignored"):
            self.service.report_ignored()

    def toggle(self) -> None:
        if self.visible:
            self.hide()
        else:
            self.show("normal")

    def _on_focus_out(self, _event) -> None:
        if self.visible:
            self.hide()

    # ---------- 按钮回调 ----------
    def _on_drink(self, amount: int) -> None:
        self.service.drink(amount)
        self._responded = True
        if self.mode == "reminder":
            self.refresh()
            self.root.after(700, self.hide)
        else:
            self.refresh()

    def _on_drink_default(self) -> None:
        self._on_drink(int(self.service.cfg.get("reminder.cup_ml", 250)))

    def _on_undo(self) -> None:
        amount = self.service.undo_last_drink()
        self._responded = True  # 在 reminder 模式下点撤销也算已响应，不计入忽略
        self.refresh()
        if amount is None:
            self.stat_lbl.config(text="今天没有可撤销的记录")

    def _on_wake(self, _event=None) -> None:
        self.service.wake_up()
        mt = self.service.morning_target()
        self.service.notifier.show_message(
            "早安 ☀️",
            f"上班前这段建议喝约 {mt}ml，先来一杯吧 💧" if mt else "起床先喝一杯水 💧",
        )
        self._responded = True
        self.refresh()

    def _on_clock_in(self, _event=None) -> None:
        """弹出预设菜单选择上班前喝了多少。"""
        menu = tk.Menu(self.root, tearoff=0)
        for ml in (0, 200, 350, 500):
            label = "没喝" if ml == 0 else f"{ml}ml"
            menu.add_command(label=f"上班前 {label}", command=lambda v=ml: self._do_clock_in(v))
        menu.add_separator()
        menu.add_command(label="自定义…", command=self._clock_in_custom)
        try:
            menu.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        finally:
            menu.grab_release()

    def _clock_in_custom(self) -> None:
        ml = simpledialog.askinteger("上班打卡", "上班前喝了多少 ml？", parent=self.root, minvalue=0, maxvalue=3000)
        if ml is not None:
            self._do_clock_in(ml)

    def _do_clock_in(self, ml: int) -> None:
        self.service.clock_in(ml)
        self._responded = True
        self.refresh()

    def _on_clock_out(self, _event=None) -> None:
        """弹出预设菜单选择几点睡，再后台算下班后建议。"""
        menu = tk.Menu(self.root, tearoff=0)
        for bt in ("22:30", "23:00", "23:30", "00:00"):
            menu.add_command(label=f"今晚约 {bt} 睡", command=lambda v=bt: self._do_clock_out(v))
        try:
            menu.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())
        finally:
            menu.grab_release()

    def _do_clock_out(self, bedtime: str) -> None:
        self._responded = True

        def _job():
            try:
                ws = self.service.clock_out(bedtime)
                aw = (ws or {}).get("after_work") or {}
                self.service.notifier.show_message(
                    "下班后安排",
                    f"还需再喝约 {aw.get('after_ml', 0)}ml\n{aw.get('advice', '')}",
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("下班打卡失败: %s", exc)

        threading.Thread(target=_job, daemon=True, name="panel-clockout").start()

    def _on_left_action(self) -> None:
        # reminder 模式下是「还没喝」；normal 模式下是「暂停/恢复提醒」
        if self.mode == "reminder":
            self._responded = True
            if hasattr(self.service, "report_ignored"):
                self.service.report_ignored()
            self.hide()
        else:
            self.service.toggle_pause()
            self.refresh()

    def _on_open_web(self) -> None:
        from .web.server import open_panel

        open_panel(self.service.cfg)

    # ---------- 命令队列轮询 ----------
    def _poll(self) -> None:
        try:
            while True:
                cmd = self.q.get_nowait()
                self._handle(cmd)
        except queue.Empty:
            pass
        self.root.after(150, self._poll)

    def _handle(self, cmd: str) -> None:
        if cmd == "toggle":
            self.toggle()
        elif cmd == "show":
            self.show("normal")
        elif cmd == "reminder":
            self.show("reminder")
        elif cmd == "hide":
            self.hide()
        elif cmd == "refresh":
            if self.visible:
                self.refresh()
        elif cmd == "quit":
            self.root.destroy()

    def run(self) -> None:
        """启动 Tk 主循环(阻塞，需在主线程调用)。"""
        self.root.mainloop()
