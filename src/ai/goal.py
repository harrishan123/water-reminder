"""智能每日饮水方案：结合体重、运动、气温与健康状况，由 AI 计算目标与建议。

优先用 AI；AI 不可用/失败时回退到经验公式：
  基础 = 体重(kg) × 30ml
  运动补偿 = none:0 / light:300 / moderate:600 / intense:1000
  气温补偿 = 气温>30°C 时每超 1°C 加 50ml(上限 +800ml)

安全：饮水量并非越多越好。肾功能不全、心衰、透析、低钠血症等需要"限水"，
AI 被要求在这类情况下置 needs_doctor=true 并给出就医提示，而不是擅自设定危险数值。
本模块输出仅为健康提示，非医疗诊断。
"""
from __future__ import annotations

import json
import logging
import re

log = logging.getLogger("water.goal")

EXERCISE_BONUS = {"none": 0, "light": 300, "moderate": 600, "intense": 1000}

GOAL_MIN, GOAL_MAX = 1200, 4000

DISCLAIMER = "以上为 AI 健康提示，非医疗诊断；如有特殊疾病请遵医嘱。"


def _formula_goal(weight_kg: float, exercise_level: str, temp_c: float) -> int:
    base = weight_kg * 30
    bonus = EXERCISE_BONUS.get(str(exercise_level).lower(), 300)
    temp_bonus = 0
    if temp_c and temp_c > 30:
        temp_bonus = min(int((temp_c - 30) * 50), 800)
    total = base + bonus + temp_bonus
    # 夹在合理区间 [1200, 4000]
    return int(max(GOAL_MIN, min(GOAL_MAX, round(total / 50) * 50)))


def _clamp_goal(value) -> int:
    try:
        return int(max(GOAL_MIN, min(GOAL_MAX, float(value))))
    except (TypeError, ValueError):
        return GOAL_MIN


def _split_phases(goal: int, active_start: str, active_end: str) -> list[dict]:
    """把全天目标按比例拆成 上班前/上班时段/上班后 三段(无 AI 时的兜底)。"""
    before = int(round(goal * 0.25 / 50) * 50)
    after = int(round(goal * 0.20 / 50) * 50)
    during = goal - before - after
    s = active_start or "上班前"
    e = active_end or "下班"
    return [
        {"label": f"上班前(起床~{s})", "ml": before, "hint": "起床一杯 + 早餐时补水"},
        {"label": f"上班时段({s}~{e})", "ml": during, "hint": "每 1–2 小时一杯，少量多次"},
        {"label": f"下班后({e}~睡前)", "ml": after, "hint": "睡前 1 小时别喝太多，减少夜尿"},
    ]


def _normalize_phases(raw, goal: int, active_start: str, active_end: str) -> list[dict]:
    """规整 AI 返回的 phases；缺失或不合法则用比例兜底。"""
    out = []
    for p in raw or []:
        if not isinstance(p, dict):
            continue
        label = str(p.get("label", "")).strip()
        try:
            ml = int(float(p.get("ml")))
        except (TypeError, ValueError):
            continue
        if label and ml >= 0:
            out.append({"label": label, "ml": ml, "hint": str(p.get("hint", "")).strip()})
    return out if len(out) >= 2 else _split_phases(goal, active_start, active_end)


def _fallback_plan(
    weight_kg: float, exercise_level: str, temp_c: float, health: str,
    active_start: str = "", active_end: str = "",
) -> dict:
    """无 AI 或解析失败时的方案：用公式算目标 + 通用建议 + 比例分段。"""
    goal = _formula_goal(weight_kg, exercise_level, temp_c)
    note = f"按公式估算(体重{weight_kg}kg, 运动{exercise_level}, 气温{temp_c}°C)"
    caution = ""
    if health.strip():
        caution = "已填健康状况，但未启用 AI，无法据此分析；如有特殊疾病请遵医嘱。"
    return {
        "goal_ml": goal,
        "note": note,
        "rhythm": "少量多次、均匀饮水，别等口渴才喝。",
        "tips": [],
        "caution": caution,
        "needs_doctor": False,
        "reminder_lines": [],  # 空 -> 调用方回退到通用提醒语
        "phases": _split_phases(goal, active_start, active_end),
    }


def compute_plan(
    ai_client,
    weight_kg: float,
    exercise_level: str,
    temp_c: float,
    health: str = "",
    active_start: str = "",
    active_end: str = "",
) -> dict:
    """返回当日饮水方案字典：
        {goal_ml, note, rhythm, tips[], caution, needs_doctor, reminder_lines[], phases[]}
    phases 把全天目标拆成 上班前/上班时段/上班后 三段，便于用户只在上班时段统计也对得上。
    """
    health = (health or "").strip()
    fallback = _fallback_plan(weight_kg, exercise_level, temp_c, health, active_start, active_end)

    if ai_client is None or not ai_client.is_enabled():
        return fallback

    system = (
        "你是专业的健康饮水顾问。根据用户的身体信息和健康状况，给出今日饮水方案。"
        "注意安全：饮水并非越多越好——肾功能不全、心力衰竭、透析、低钠血症等情况需要限制饮水，"
        "遇到这类情况请把 needs_doctor 设为 true，并在 caution 里提示就医，不要擅自给出过低或危险的数值。"
        "用户主要在上班/活跃时段内记录喝水，所以请把全天目标拆成三段(上班前、上班时段、下班后)，"
        "三段 ml 之和约等于 goal_ml，方便用户对照。"
        "只返回 JSON，不要多余文字，格式严格为："
        '{"goal_ml": 整数(1200-4000), '
        '"rhythm": "一句话喝水节奏建议", '
        '"tips": ["针对其健康状况的具体提示", ...](1-4条，没有则空数组), '
        '"caution": "需要注意或就医的提醒，没有则空字符串", '
        '"needs_doctor": true或false, '
        '"reminder_lines": ["亲切的提醒语，结合其健康状况，不要出现具体毫升数字", ...](3-5条，每条不超过30字), '
        '"phases": [{"label":"上班前(起床~上班)","ml":整数,"hint":"简短提示"}, '
        '{"label":"上班时段","ml":整数,"hint":"..."}, {"label":"下班后(~睡前)","ml":整数,"hint":"..."}]}'
    )
    window = f"{active_start or '上午'}–{active_end or '晚上'}"
    user = (
        f"体重: {weight_kg} kg\n"
        f"运动量: {exercise_level} (none/light/moderate/intense)\n"
        f"当日气温: {temp_c} °C\n"
        f"健康状况: {health or '无特殊'}\n"
        f"上班/活跃(主要记录)时段: {window}\n"
        "请给出今日饮水方案，并按上班前/上班时段/下班后分三段给出毫升数。"
    )
    text = ai_client.chat(system, user, temperature=0.5)
    if not text:
        return fallback

    parsed = _extract_json(text)
    if not isinstance(parsed, dict) or "goal_ml" not in parsed:
        log.warning("AI 方案无法解析，使用公式兜底: %s", text[:120])
        return fallback

    goal = _clamp_goal(parsed.get("goal_ml"))
    rhythm = str(parsed.get("rhythm", "")).strip() or "少量多次、均匀饮水。"
    tips = [str(t).strip() for t in (parsed.get("tips") or []) if str(t).strip()][:4]
    caution = str(parsed.get("caution", "")).strip()
    needs_doctor = bool(parsed.get("needs_doctor", False))
    lines = [str(s).strip() for s in (parsed.get("reminder_lines") or []) if str(s).strip()][:5]
    phases = _normalize_phases(parsed.get("phases"), goal, active_start, active_end)

    note = rhythm if not health else f"已结合健康状况：{rhythm}"
    return {
        "goal_ml": goal,
        "note": note,
        "rhythm": rhythm,
        "tips": tips,
        "caution": caution,
        "needs_doctor": needs_doctor,
        "reminder_lines": lines,
        "phases": phases,
    }


def _extract_json(text: str) -> dict | None:
    """从可能含多余文本的回复中提取第一个 JSON 对象。"""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None
