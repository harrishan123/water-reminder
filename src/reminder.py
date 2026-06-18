"""核心服务：调度提醒、管理喝水记录、生成与推送报告。

AppService 把 config / storage / notifier / ai 串起来，供托盘和调度器调用。
"""
from __future__ import annotations

import json
import logging
import random
from datetime import date, datetime, time, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.base import JobLookupError

from . import __version__
from .ai import goal as goal_mod
from .ai import report as report_mod
from .ai.client import build_client
from .notifier import Notifier
from .storage import Storage
from . import weather

log = logging.getLogger("water.reminder")

REMINDER_LINES = [
    "该喝水啦！给身体补充点水分吧 💧",
    "停一停，喝口水，眼睛和身体都需要休息～",
    "你的小水杯在召唤你，来一杯吧！",
    "补水时间到，喝水让你更专注。",
    "久坐别忘喝水，起来活动一下顺便接杯水。",
]


def _in_time_window(t: time, start: time, end: time) -> bool:
    """t 是否落在 [start, end] 区间内，支持跨午夜(start>end，如 22:00–02:00)。"""
    if start <= end:
        return start <= t <= end
    return t >= start or t <= end


class AppService:
    def __init__(self, cfg):
        self.cfg = cfg
        self.storage = Storage()
        self.notifier = Notifier(cfg)
        self.ai = build_client(cfg)
        self.scheduler = BackgroundScheduler()
        self._paused = False
        self.on_progress_changed = None  # 可选回调，进度变化时调用
        self.on_reminder = None  # 可选回调，到提醒时间时调用(弹小面板)
        self.last_reminder_text = ""  # 最近一次提醒文案，供小面板展示
        self._ignored_count = 0  # 当天未响应的提醒数
        self._ignored_day = date.today()  # 计数对应的日期(跨天清零)
        self._cached_temp: float | None = None  # 当日气温缓存
        self._cached_temp_day: date | None = None  # 气温缓存对应的日期(跨天失效)
        self._report_cache: dict[tuple, str] = {}  # 报告缓存 {(kind, 日期): 文本}
        self._plan: dict | None = None  # 当日健康方案缓存(目标/建议/提醒文案)

    # ---------- 生命周期 ----------
    def start(self) -> None:
        self.ensure_today_goal()
        # 启动不立刻弹窗打扰，首次提醒排在一个间隔之后
        self._schedule_reminders(immediate=False)
        self._schedule_reports()
        self.scheduler.start()
        log.info("调度器已启动")

    def shutdown(self) -> None:
        try:
            self.scheduler.shutdown(wait=False)
        except Exception:  # noqa: BLE001
            pass
        self.storage.close()

    # ---------- 目标与健康方案 ----------
    def ensure_today_goal(self) -> int:
        """确保今天有目标值，返回目标毫升。"""
        return int(self.today_plan().get("goal_ml", 0))

    def today_plan(self) -> dict:
        """返回今日健康方案(含目标/建议/提醒文案)。优先用内存与存储缓存，缺失才调用 AI。"""
        today = date.today().isoformat()
        if self._plan is not None and self._plan.get("day") == today:
            return self._plan
        raw = self.storage.get_plan()
        if raw:
            try:
                plan = json.loads(raw)
                plan["day"] = today
                self._plan = plan
                return plan
            except (json.JSONDecodeError, TypeError):
                pass
        self._plan = self._compute_plan()
        return self._plan

    def _health_text(self) -> str:
        """把勾选的健康状况与自由文本拼成一段给 AI 的描述。"""
        conds = self.cfg.get("profile.health_conditions", []) or []
        if isinstance(conds, str):
            conds = [conds]
        parts = [str(c).strip() for c in conds if str(c).strip()]
        notes = str(self.cfg.get("profile.health_notes", "") or "").strip()
        if notes:
            parts.append(notes)
        return "；".join(parts)

    def _compute_plan(self) -> dict:
        """调用 AI(或公式兜底)计算今日方案，并持久化目标与方案。"""
        temp = self.current_temperature()
        weight = float(self.cfg.get("profile.weight_kg", 65))
        level = str(self.cfg.get("profile.exercise_level", "light"))
        health = self._health_text()
        plan = goal_mod.compute_plan(self.ai, weight, level, temp or 0.0, health)

        fixed = int(self.cfg.get("profile.daily_goal_ml", 0) or 0)
        if fixed > 0:  # 用户设了固定目标，则覆盖 AI 的数值(但保留建议/提醒)
            plan["goal_ml"] = fixed
            base = plan.get("note", "")
            plan["note"] = "固定目标" + (f"；{base}" if base else "")

        plan["day"] = date.today().isoformat()
        self.storage.set_goal(int(plan["goal_ml"]), note=plan.get("note", ""))
        self.storage.set_plan(json.dumps(plan, ensure_ascii=False))
        log.info("今日目标: %sml (%s)", plan["goal_ml"], plan.get("note", ""))
        return plan

    def recompute_goal(self) -> int:
        """清空今日方案与气温缓存并重新计算(供托盘/网页「重算目标」调用)。"""
        self.storage.clear_plan()
        self._plan = None
        self._cached_temp = None
        self._cached_temp_day = None
        self._report_cache.clear()  # 目标变了，完成率/报告需重算
        return self.ensure_today_goal()

    def current_temperature(self) -> float | None:
        """返回当日气温(摄氏度)。缓存按日期失效，跨天后会重新获取。"""
        today = date.today()
        if self._cached_temp is None or self._cached_temp_day != today:
            try:
                self._cached_temp = weather.get_temperature(self.cfg)
                self._cached_temp_day = today
            except Exception as exc:  # noqa: BLE001
                log.warning("获取气温失败: %s", exc)
                return None
        return self._cached_temp

    # ---------- 喝水记录 ----------
    def drink(self, amount_ml: int | None = None) -> None:
        amount = int(amount_ml or self.cfg.get("reminder.cup_ml", 250))
        self.storage.add_intake(amount)
        total = self.storage.total_for_day()
        goal = self.storage.get_goal() or 0
        log.info("记录喝水 %sml，今日累计 %s/%sml", amount, total, goal)
        self._report_cache.clear()  # 数据变了，报告需重算
        self._reset_reminder_timer()  # 刚喝完，从现在起重新计时
        if callable(self.on_progress_changed):
            self.on_progress_changed()

    def undo_last_drink(self) -> int | None:
        """撤销今天最近一次喝水记录，返回被撤销的毫升数(无记录返回 None)。"""
        amount = self.storage.delete_last_intake()
        if amount is None:
            return None
        log.info("撤销喝水 %sml", amount)
        self._report_cache.clear()
        if callable(self.on_progress_changed):
            self.on_progress_changed()
        return amount

    def progress_text(self) -> str:
        s = self.status()
        return f"今日 {s['total']}/{s['goal']}ml ({s['pct']}%) · {s['count']} 杯"

    # ---------- 状态(供 Web 面板) ----------
    def status(self) -> dict:
        total = self.storage.total_for_day()
        goal = self.storage.get_goal() or self.ensure_today_goal()
        count = self.storage.count_for_day()
        pct = int(total / goal * 100) if goal else 0
        info = self.storage.get_goal_info()
        plan = self.today_plan()
        return {
            "total": total,
            "goal": goal,
            "count": count,
            "pct": pct,
            "cup_ml": int(self.cfg.get("reminder.cup_ml", 250)),
            "version": __version__,
            "paused": self._paused,
            "streak": self.storage.current_streak(),
            "ignored": self.ignored_count,
            "ai_enabled": self.ai.is_enabled(),
            "week": self.storage.week_summary(),
            "hourly": self.storage.hourly_distribution(),
            "interval_minutes": int(self.cfg.get("reminder.interval_minutes", 60)),
            "goal_note": info["note"],
            "weather": {
                "enabled": bool(self.cfg.get("weather.enabled", False)),
                "city": str(self.cfg.get("weather.city", "")),
                "provider": str(self.cfg.get("weather.provider", "wttr")),
                "temperature": self.current_temperature(),
            },
            "health": {
                "conditions": self._health_text(),
                "rhythm": plan.get("rhythm", ""),
                "tips": plan.get("tips", []),
                "caution": plan.get("caution", ""),
                "needs_doctor": bool(plan.get("needs_doctor", False)),
                "analyzed": bool(self._health_text()) and self.ai.is_enabled(),
                "disclaimer": goal_mod.DISCLAIMER,
            },
        }

    def reload_config(self) -> None:
        """从磁盘重新加载配置并重新调度(供保存设置后调用)。"""
        from .config import load_config

        fresh = load_config()
        self.cfg.replace(fresh.data)
        # 体重/健康状况等可能变了，清掉今日方案缓存，下次按新配置重算
        self.storage.clear_plan()
        self._plan = None
        self._report_cache.clear()
        self._reschedule()
        log.info("配置已重新加载并应用")

    def _reschedule(self) -> None:
        """按当前配置重建定时任务。"""
        for job_id in ("reminder", "daily", "weekly"):
            job = self.scheduler.get_job(job_id)
            if job:
                job.remove()
        self._schedule_reminders()
        self._schedule_reports()

    # ---------- 暂停/恢复 ----------
    @property
    def paused(self) -> bool:
        return self._paused

    def toggle_pause(self) -> bool:
        self._paused = not self._paused
        log.info("提醒已%s", "暂停" if self._paused else "恢复")
        return self._paused

    # ---------- 调度 ----------
    def _schedule_reminders(self, immediate: bool = False) -> None:
        # 周期触发：稳定地每隔 N 分钟提醒一次(忽略也会持续提醒)。
        # 自适应靠喝水时 _reset_reminder_timer() 把下次触发往后推实现。
        # immediate=True 仅供调试，立刻先弹一次；否则首次提醒在一个间隔之后(启动不打扰)。
        interval = max(1, int(self.cfg.get("reminder.interval_minutes", 60)))
        kwargs = {"next_run_time": datetime.now()} if immediate else {}
        self.scheduler.add_job(
            self._fire_reminder,
            "interval",
            minutes=interval,
            id="reminder",
            replace_existing=True,
            **kwargs,
        )

    def _reset_reminder_timer(self) -> None:
        """把下一次提醒推迟到现在 + 间隔分钟(喝水后调用，实现"喝完重新计时")。

        之后仍按 interval 周期继续，所以即便一直不喝也会持续提醒，不会中断。
        """
        interval = max(1, int(self.cfg.get("reminder.interval_minutes", 60)))
        run_at = datetime.now() + timedelta(minutes=interval)
        try:
            self.scheduler.modify_job("reminder", next_run_time=run_at)
        except JobLookupError:
            self._schedule_reminders()

    def _schedule_reports(self) -> None:
        daily = self.cfg.parse_time("report.daily_time", "21:30")
        if daily:
            self.scheduler.add_job(
                self.send_daily_report,
                "cron",
                hour=daily.hour,
                minute=daily.minute,
                id="daily",
                replace_existing=True,
            )
        weekly = self.cfg.parse_time("report.weekly_time", "20:00")
        weekday = str(self.cfg.get("report.weekly_weekday", "sun"))
        if weekly:
            self.scheduler.add_job(
                self.send_weekly_report,
                "cron",
                day_of_week=weekday,
                hour=weekly.hour,
                minute=weekly.minute,
                id="weekly",
                replace_existing=True,
            )

    def _fire_reminder(self) -> None:
        # interval 触发会自动安排下一次，这里只判断是否真的弹出
        if self._paused or not self._within_active_hours():
            return
        # 优先用 AI 结合健康状况生成的个性化提醒语，没有则用通用句
        lines = (self._plan or {}).get("reminder_lines") or REMINDER_LINES
        self.last_reminder_text = random.choice(lines)
        # 优先弹右下角小面板；无面板(如纯后台)时退回系统通知
        if callable(self.on_reminder):
            self.on_reminder()
        else:
            body = self.last_reminder_text + "\n" + self.progress_text()
            self.notifier.show_reminder("喝水提醒", body, on_drink=self.drink)

    @property
    def ignored_count(self) -> int:
        """当天的忽略次数(跨天自动清零)。"""
        if self._ignored_day != date.today():
            self._ignored_day = date.today()
            self._ignored_count = 0
        return self._ignored_count

    def report_ignored(self) -> None:
        """面板被关闭却没记录喝水时调用(默认视为没喝)。"""
        self._ignored_count = self.ignored_count + 1  # 经 property 先做跨天清零
        log.info("提醒被忽略(默认未喝水)，今日累计 %s 次", self._ignored_count)

    def _within_active_hours(self, now: datetime | None = None) -> bool:
        now_t = (now or datetime.now()).time()
        start = self.cfg.parse_time("reminder.active_start", "09:00") or time(9, 0)
        end = self.cfg.parse_time("reminder.active_end", "22:00") or time(22, 0)
        if not _in_time_window(now_t, start, end):  # 支持跨午夜时段
            return False
        # 勿扰时段(同样支持跨午夜)
        q_start = self.cfg.parse_time("reminder.quiet_start", "")
        q_end = self.cfg.parse_time("reminder.quiet_end", "")
        if q_start and q_end and _in_time_window(now_t, q_start, q_end):
            return False
        return True

    # ---------- 报告 ----------
    def send_daily_report(self, force: bool = False) -> str:
        """生成并推送日报。force=True 忽略缓存，强制重新调用 AI。"""
        key = ("daily", date.today().isoformat())
        if force or key not in self._report_cache:
            self._report_cache[key] = report_mod.build_daily_report(
                self.storage, self.ai, ignored=self.ignored_count
            )
        content = self._report_cache[key]
        self.notifier.push_report("喝水日报", content)
        return content

    def send_weekly_report(self, force: bool = False) -> str:
        """生成并推送周报。force=True 忽略缓存，强制重新调用 AI。"""
        key = ("weekly", date.today().isoformat())
        if force or key not in self._report_cache:
            self._report_cache[key] = report_mod.build_weekly_report(self.storage, self.ai)
        content = self._report_cache[key]
        self.notifier.push_report("喝水周报", content)
        return content
