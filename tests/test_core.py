"""核心逻辑单元测试。运行：python -m unittest discover -s tests

只依赖标准库 unittest，不需要额外安装。storage 测试一律用临时数据库，
不会触碰真实的 data/water.db。
"""
import os
import sys
import tempfile
import unittest
from datetime import date, time, timedelta

# 让 `import src.xxx` 在仓库根目录下可用
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ai import goal as goal_mod
from src.config import Config, _deep_merge
from src.reminder import _in_time_window
from src.storage import Storage


class TestFormulaGoal(unittest.TestCase):
    def test_basic_formula(self):
        # 65kg 轻度运动 22°C: 65*30 + 300 = 2250
        self.assertEqual(goal_mod._formula_goal(65, "light", 22), 2250)

    def test_clamped_range(self):
        self.assertGreaterEqual(goal_mod._formula_goal(10, "none", 0), 1200)
        self.assertLessEqual(goal_mod._formula_goal(300, "intense", 45), 4000)

    def test_high_temp_bonus(self):
        cool = goal_mod._formula_goal(70, "light", 20)
        hot = goal_mod._formula_goal(70, "light", 36)
        self.assertGreater(hot, cool)

    def test_clamp_goal_handles_garbage(self):
        self.assertEqual(goal_mod._clamp_goal("abc"), goal_mod.GOAL_MIN)
        self.assertEqual(goal_mod._clamp_goal(99999), goal_mod.GOAL_MAX)


class TestFallbackPlan(unittest.TestCase):
    def test_fallback_shape(self):
        # ai_client=None -> 走兜底，返回完整结构
        plan = goal_mod.compute_plan(None, 70, "light", 22, "尿酸偏高", "10:00", "22:00")
        for key in ("goal_ml", "note", "rhythm", "tips", "caution", "needs_doctor", "reminder_lines", "phases"):
            self.assertIn(key, plan)
        self.assertGreaterEqual(plan["goal_ml"], goal_mod.GOAL_MIN)
        # 填了健康状况但无 AI -> caution 提示
        self.assertTrue(plan["caution"])
        # 分段：三段且总和约等于目标
        self.assertEqual(len(plan["phases"]), 3)
        self.assertAlmostEqual(sum(p["ml"] for p in plan["phases"]), plan["goal_ml"], delta=100)


class TestTimeWindow(unittest.TestCase):
    def test_normal_window(self):
        self.assertTrue(_in_time_window(time(12, 0), time(9, 0), time(22, 0)))
        self.assertFalse(_in_time_window(time(8, 0), time(9, 0), time(22, 0)))

    def test_overnight_window(self):
        # 22:00–02:00 跨午夜
        self.assertTrue(_in_time_window(time(23, 30), time(22, 0), time(2, 0)))
        self.assertTrue(_in_time_window(time(1, 0), time(22, 0), time(2, 0)))
        self.assertFalse(_in_time_window(time(12, 0), time(22, 0), time(2, 0)))


class TestConfig(unittest.TestCase):
    def test_deep_merge(self):
        base = {"a": {"x": 1, "y": 2}, "b": 3}
        merged = _deep_merge(base, {"a": {"y": 20}, "c": 4})
        self.assertEqual(merged["a"], {"x": 1, "y": 20})
        self.assertEqual(merged["b"], 3)
        self.assertEqual(merged["c"], 4)
        # 不应改动原始 base
        self.assertEqual(base["a"]["y"], 2)

    def test_parse_time(self):
        cfg = Config({"r": {"t": "08:30", "empty": ""}})
        self.assertEqual(cfg.parse_time("r.t"), time(8, 30))
        self.assertIsNone(cfg.parse_time("r.empty"))
        self.assertIsNone(cfg.parse_time("r.missing"))


class TestStorage(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.path)
        self.s = Storage(self.path)

    def tearDown(self):
        self.s.close()
        if os.path.exists(self.path):
            os.remove(self.path)

    def test_intake_and_total(self):
        self.s.add_intake(200)
        self.s.add_intake(150)
        self.assertEqual(self.s.total_for_day(), 350)
        self.assertEqual(self.s.count_for_day(), 2)

    def test_undo_last(self):
        self.s.add_intake(200)
        self.s.add_intake(150)
        self.assertEqual(self.s.delete_last_intake(), 150)
        self.assertEqual(self.s.total_for_day(), 200)
        # 删空后返回 None
        self.s.delete_last_intake()
        self.assertIsNone(self.s.delete_last_intake())

    def test_goal_and_streak(self):
        today = date.today()
        yest = today - timedelta(days=1)
        for d in (yest, today):
            self.s.set_goal(1000, day=d)
            self.s.add_intake(1000, when=__import__("datetime").datetime.combine(d, time(10, 0)))
        self.assertEqual(self.s.current_streak(), 2)

    def test_week_summary_len(self):
        self.s.set_goal(2000)
        self.s.add_intake(500)
        week = self.s.week_summary()
        self.assertEqual(len(week), 7)
        self.assertEqual(week[-1]["total"], 500)

    def test_list_and_delete_intake(self):
        self.s.add_intake(200)
        self.s.add_intake(150)
        items = self.s.list_intakes()
        self.assertEqual(len(items), 2)
        self.assertEqual(self.s.delete_intake(items[0]["id"]), 200)
        self.assertEqual(self.s.count_for_day(), 1)
        self.assertIsNone(self.s.delete_intake(999999))

    def test_range_summary(self):
        self.s.set_goal(1000)
        self.s.add_intake(1000)
        r = self.s.range_summary(30)
        self.assertEqual(r["days"], 30)
        self.assertEqual(r["achieved_days"], 1)
        self.assertEqual(r["tracked_days"], 1)
        self.assertGreaterEqual(r["total"], 1000)

    def test_plan_roundtrip(self):
        self.assertIsNone(self.s.get_plan())
        self.s.set_plan('{"goal_ml": 2500}')
        self.assertEqual(self.s.get_plan(), '{"goal_ml": 2500}')
        self.s.clear_plan()
        self.assertIsNone(self.s.get_plan())


if __name__ == "__main__":
    unittest.main()
