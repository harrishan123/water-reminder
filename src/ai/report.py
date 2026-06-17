"""日报/周报生成。AI 生成个性化健康建议，失败时用模板兜底。"""
from __future__ import annotations

import logging
from datetime import date

log = logging.getLogger("water.report")


def _format_hourly(dist: dict[int, int]) -> str:
    if not dist:
        return "今天还没有喝水记录"
    parts = [f"{h:02d}点 {ml}ml" for h, ml in sorted(dist.items())]
    return "，".join(parts)


def build_daily_report(storage, ai_client, day: date | None = None, ignored: int = 0) -> str:
    """生成日报文本(纯文本，适合通知/推送)。"""
    day = day or date.today()
    total = storage.total_for_day(day)
    goal = storage.get_goal(day) or 0
    count = storage.count_for_day(day)
    dist = storage.hourly_distribution(day)
    streak = storage.current_streak(day)
    pct = int(total / goal * 100) if goal else 0

    stats = (
        f"日期: {day.isoformat()}\n"
        f"今日饮水: {total}ml / 目标 {goal}ml ({pct}%)\n"
        f"喝水次数: {count} 次\n"
        f"时间分布: {_format_hourly(dist)}\n"
        f"连续达标: {streak} 天"
    )
    if ignored:
        stats += f"\n忽略提醒: {ignored} 次"

    advice = _ai_advice(
        ai_client,
        scope="今日",
        stats=stats,
    )
    return f"【喝水日报】\n{stats}\n\n建议: {advice}"


def build_weekly_report(storage, ai_client, end_day: date | None = None) -> str:
    end_day = end_day or date.today()
    week = storage.week_summary(end_day)
    achieved_days = sum(1 for d in week if d["achieved"])
    avg = int(sum(d["total"] for d in week) / max(1, len(week)))
    streak = storage.current_streak(end_day)

    lines = [
        f"{d['day']}: {d['total']}ml/{d['goal']}ml {'达标' if d['achieved'] else '未达标'}"
        for d in week
    ]
    stats = (
        f"近 7 天达标: {achieved_days}/7 天\n"
        f"日均饮水: {avg}ml\n"
        f"当前连续达标: {streak} 天\n"
        + "\n".join(lines)
    )
    advice = _ai_advice(ai_client, scope="本周", stats=stats)
    return f"【喝水周报】\n{stats}\n\n建议: {advice}"


def _ai_advice(ai_client, scope: str, stats: str) -> str:
    if ai_client is not None and ai_client.is_enabled():
        system = (
            "你是亲切的健康饮水教练。根据用户的喝水统计，给出 1-3 句"
            "具体、鼓励性的健康建议(中文，不超过80字)，不要重复罗列数据。"
        )
        user = f"这是用户{scope}的喝水统计:\n{stats}\n请给出建议。"
        text = ai_client.chat(system, user, temperature=0.8)
        if text:
            return text
    return _template_advice(stats)


def _template_advice(stats: str) -> str:
    """无 AI 时的模板建议，根据完成率简单分级。"""
    pct = 0
    for line in stats.splitlines():
        if "%" in line:
            try:
                pct = int(line.split("(")[-1].split("%")[0])
            except (ValueError, IndexError):
                pass
            break
    if pct >= 100:
        return "今天喝水目标已达成，非常棒！保持均匀饮水的好习惯。"
    if pct >= 60:
        return "完成得不错，离目标只差一点，睡前别忘了再补充一些水分。"
    return "今天喝水偏少啦，建议设置更频繁的提醒，每次小口多次补水更健康。"
