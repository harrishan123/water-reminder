"""智能每日饮水目标计算。

优先用 AI 计算；AI 不可用/失败时回退到经验公式：
  基础 = 体重(kg) × 30ml
  运动补偿 = none:0 / light:300 / moderate:600 / intense:1000
  气温补偿 = 气温>30°C 时每超 1°C 加 50ml(上限 +800ml)
"""
from __future__ import annotations

import json
import logging
import re

log = logging.getLogger("water.goal")

EXERCISE_BONUS = {"none": 0, "light": 300, "moderate": 600, "intense": 1000}


def _formula_goal(weight_kg: float, exercise_level: str, temp_c: float) -> int:
    base = weight_kg * 30
    bonus = EXERCISE_BONUS.get(str(exercise_level).lower(), 300)
    temp_bonus = 0
    if temp_c and temp_c > 30:
        temp_bonus = min(int((temp_c - 30) * 50), 800)
    total = base + bonus + temp_bonus
    # 夹在合理区间 [1200, 4000]
    return int(max(1200, min(4000, round(total / 50) * 50)))


def compute_daily_goal(
    ai_client,
    weight_kg: float,
    exercise_level: str,
    temp_c: float,
) -> tuple[int, str]:
    """返回 (目标毫升, 说明文字)。"""
    fallback = _formula_goal(weight_kg, exercise_level, temp_c)

    if ai_client is None or not ai_client.is_enabled():
        return fallback, f"按公式估算(体重{weight_kg}kg, 运动{exercise_level}, 气温{temp_c}°C)"

    system = (
        "你是专业的健康饮水顾问。请根据用户信息计算今日推荐饮水量(毫升)，"
        "并给出一句简短的喝水节奏建议。只返回 JSON，格式: "
        '{"goal_ml": 整数, "advice": "一句话建议"}。'
        "饮水量应在 1200-4000 毫升的合理范围内。"
    )
    user = (
        f"体重: {weight_kg} kg\n"
        f"运动量: {exercise_level} (none/light/moderate/intense)\n"
        f"当日气温: {temp_c} °C\n"
        "请计算今日推荐饮水量。"
    )
    text = ai_client.chat(system, user, temperature=0.4)
    if not text:
        return fallback, f"AI 不可用，按公式估算 {fallback}ml"

    parsed = _extract_json(text)
    if parsed and isinstance(parsed.get("goal_ml"), (int, float)):
        goal = int(max(1200, min(4000, parsed["goal_ml"])))
        advice = str(parsed.get("advice", "")).strip() or "记得均匀饮水哦"
        return goal, advice

    log.warning("AI 返回无法解析，使用公式兜底: %s", text[:100])
    return fallback, f"按公式估算 {fallback}ml"


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
