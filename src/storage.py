"""SQLite 存储：喝水记录与统计查询。数据全部保存在本地。"""
from __future__ import annotations

import os
import sqlite3
import threading
from datetime import date, datetime, timedelta
from typing import Optional

from .config import DATA_DIR

DB_PATH = os.path.join(DATA_DIR, "water.db")


class Storage:
    """喝水记录的持久化与统计。

    单连接配合 check_same_thread=False 在多线程(主线程/托盘/Web/调度器)间共享，
    所有读写都用一把可重入锁串行化，避免并发触发 database is locked 或游标冲突。
    """

    def __init__(self, db_path: str | None = None):
        os.makedirs(DATA_DIR, exist_ok=True)
        self._conn = sqlite3.connect(db_path or DB_PATH, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()  # 可重入：week_summary 等会嵌套调用其他读方法
        self._init_db()

    def _init_db(self) -> None:
        cur = self._conn.cursor()
        # 每次喝水的明细记录
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS intake (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,          -- ISO 时间戳
                day TEXT NOT NULL,         -- YYYY-MM-DD，便于按天聚合
                amount_ml INTEGER NOT NULL
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_intake_day ON intake(day)")
        # 每日目标(毫升)，每天一条
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_goal (
                day TEXT PRIMARY KEY,
                goal_ml INTEGER NOT NULL,
                note TEXT
            )
            """
        )
        # 每日健康方案(AI 分析结果的 JSON)，每天一条，避免重复调用 AI
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_plan (
                day TEXT PRIMARY KEY,
                plan_json TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    # ---------- 写入 ----------
    def add_intake(self, amount_ml: int, when: datetime | None = None) -> None:
        when = when or datetime.now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO intake (ts, day, amount_ml) VALUES (?, ?, ?)",
                (when.isoformat(timespec="seconds"), when.date().isoformat(), int(amount_ml)),
            )
            self._conn.commit()

    def list_intakes(self, day: date | None = None) -> list[dict]:
        """返回某天的全部喝水明细 [{id, time, amount_ml}]，按时间正序。"""
        day = day or date.today()
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, ts, amount_ml FROM intake WHERE day=? ORDER BY id",
                (day.isoformat(),),
            ).fetchall()
        out = []
        for r in rows:
            try:
                hm = datetime.fromisoformat(r["ts"]).strftime("%H:%M")
            except ValueError:
                hm = ""
            out.append({"id": int(r["id"]), "time": hm, "amount_ml": int(r["amount_ml"])})
        return out

    def delete_intake(self, intake_id: int) -> Optional[int]:
        """按 id 删除一条喝水记录，返回被删的毫升数；不存在返回 None。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT amount_ml FROM intake WHERE id=?", (int(intake_id),)
            ).fetchone()
            if not row:
                return None
            self._conn.execute("DELETE FROM intake WHERE id=?", (int(intake_id),))
            self._conn.commit()
            return int(row["amount_ml"])

    def range_summary(self, days: int = 30, end_day: date | None = None) -> dict:
        """返回最近 N 天的汇总：{days, total, avg, achieved_days, tracked_days}。"""
        end_day = end_day or date.today()
        days = max(1, int(days))
        total = 0
        achieved = 0
        tracked = 0
        with self._lock:
            for offset in range(days):
                d = end_day - timedelta(days=offset)
                t = self.total_for_day(d)
                g = self.get_goal(d) or 0
                total += t
                if g:  # 当天设过目标才算入"有记录"
                    tracked += 1
                    if t >= g:
                        achieved += 1
        return {
            "days": days,
            "total": total,
            "avg": int(total / days),
            "achieved_days": achieved,
            "tracked_days": tracked,
        }

    def delete_last_intake(self, day: date | None = None) -> Optional[int]:
        """删除指定日期最近一条喝水记录，返回其毫升数；无记录返回 None。"""
        day = day or date.today()
        with self._lock:
            row = self._conn.execute(
                "SELECT id, amount_ml FROM intake WHERE day=? ORDER BY id DESC LIMIT 1",
                (day.isoformat(),),
            ).fetchone()
            if not row:
                return None
            self._conn.execute("DELETE FROM intake WHERE id=?", (row["id"],))
            self._conn.commit()
            return int(row["amount_ml"])

    def set_goal(self, goal_ml: int, day: date | None = None, note: str = "") -> None:
        day = day or date.today()
        with self._lock:
            self._conn.execute(
                "INSERT INTO daily_goal (day, goal_ml, note) VALUES (?, ?, ?) "
                "ON CONFLICT(day) DO UPDATE SET goal_ml=excluded.goal_ml, note=excluded.note",
                (day.isoformat(), int(goal_ml), note),
            )
            self._conn.commit()

    def set_plan(self, plan_json: str, day: date | None = None) -> None:
        day = day or date.today()
        with self._lock:
            self._conn.execute(
                "INSERT INTO daily_plan (day, plan_json) VALUES (?, ?) "
                "ON CONFLICT(day) DO UPDATE SET plan_json=excluded.plan_json",
                (day.isoformat(), plan_json),
            )
            self._conn.commit()

    def clear_plan(self, day: date | None = None) -> None:
        day = day or date.today()
        with self._lock:
            self._conn.execute("DELETE FROM daily_plan WHERE day=?", (day.isoformat(),))
            self._conn.commit()

    # ---------- 读取 ----------
    def get_plan(self, day: date | None = None) -> Optional[str]:
        day = day or date.today()
        with self._lock:
            row = self._conn.execute(
                "SELECT plan_json FROM daily_plan WHERE day=?", (day.isoformat(),)
            ).fetchone()
        return row["plan_json"] if row else None

    def get_goal(self, day: date | None = None) -> Optional[int]:
        day = day or date.today()
        with self._lock:
            row = self._conn.execute(
                "SELECT goal_ml FROM daily_goal WHERE day=?", (day.isoformat(),)
            ).fetchone()
        return int(row["goal_ml"]) if row else None

    def get_goal_info(self, day: date | None = None) -> dict:
        """返回 {goal, note} 字典；记录不存在时 goal=0, note=''。"""
        day = day or date.today()
        with self._lock:
            row = self._conn.execute(
                "SELECT goal_ml, note FROM daily_goal WHERE day=?", (day.isoformat(),)
            ).fetchone()
        if not row:
            return {"goal": 0, "note": ""}
        return {"goal": int(row["goal_ml"]), "note": row["note"] or ""}

    def total_for_day(self, day: date | None = None) -> int:
        day = day or date.today()
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(amount_ml), 0) AS total FROM intake WHERE day=?",
                (day.isoformat(),),
            ).fetchone()
        return int(row["total"])

    def count_for_day(self, day: date | None = None) -> int:
        day = day or date.today()
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS c FROM intake WHERE day=?", (day.isoformat(),)
            ).fetchone()
        return int(row["c"])

    def hourly_distribution(self, day: date | None = None) -> dict[int, int]:
        """返回 {小时: 毫升} 的当日时间分布。"""
        day = day or date.today()
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, amount_ml FROM intake WHERE day=?", (day.isoformat(),)
            ).fetchall()
        dist: dict[int, int] = {}
        for row in rows:
            hour = datetime.fromisoformat(row["ts"]).hour
            dist[hour] = dist.get(hour, 0) + int(row["amount_ml"])
        return dist

    def week_summary(self, end_day: date | None = None) -> list[dict]:
        """返回最近 7 天(含当天)的 [{day, total, goal, achieved}]。"""
        end_day = end_day or date.today()
        result: list[dict] = []
        with self._lock:  # 让 7 天读取构成一个原子快照
            for offset in range(6, -1, -1):
                d = end_day - timedelta(days=offset)
                total = self.total_for_day(d)
                goal = self.get_goal(d) or 0
                result.append(
                    {
                        "day": d.isoformat(),
                        "total": total,
                        "goal": goal,
                        "achieved": bool(goal and total >= goal),
                    }
                )
        return result

    def current_streak(self, end_day: date | None = None) -> int:
        """连续达标天数(从 end_day 往前数)。"""
        end_day = end_day or date.today()
        streak = 0
        d = end_day
        with self._lock:  # 原子快照，避免连续读取期间被写入打断
            while True:
                goal = self.get_goal(d)
                if not goal:
                    break
                if self.total_for_day(d) >= goal:
                    streak += 1
                    d -= timedelta(days=1)
                else:
                    break
        return streak

    def close(self) -> None:
        with self._lock:
            self._conn.close()
