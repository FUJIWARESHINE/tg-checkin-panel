"""调度表达式解析：cron / 每日定点 / 间隔。"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from croniter import croniter

INTERVAL_RE = re.compile(r"^(\d+)\s*(s|m|h|d)$", re.IGNORECASE)
DAILY_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


class ScheduleError(ValueError):
    pass


def parse_interval(value: str) -> int:
    match = INTERVAL_RE.match(value.strip())
    if not match:
        raise ScheduleError(f"间隔表达式不合法：{value}（示例：30m / 12h / 1d）")
    amount, unit = match.groups()
    seconds = int(amount) * _UNITS[unit.lower()]
    if seconds < 30:
        raise ScheduleError("间隔不能小于 30 秒")
    return seconds


def normalize_cron(value: str) -> str:
    """标准化为 5 或 6 字段（6 字段含秒）。"""
    parts = value.split()
    if len(parts) not in (5, 6):
        raise ScheduleError(f"Cron 表达式需要 5 或 6 个字段，当前 {len(parts)} 个")
    if not croniter.is_valid(" ".join(parts)):
        raise ScheduleError(f"Cron 表达式不合法：{value}")
    return " ".join(parts)


def daily_to_cron(value: str) -> str:
    match = DAILY_RE.match(value.strip())
    if not match:
        raise ScheduleError(f"每日定点格式应为 HH:MM 或 HH:MM:SS，当前：{value}")
    hour, minute, second = match.group(1), match.group(2), match.group(3) or "0"
    if not (0 <= int(hour) <= 23 and 0 <= int(minute) <= 59 and 0 <= int(second) <= 59):
        raise ScheduleError(f"时间超出范围：{value}")
    return f"{int(minute)} {int(hour)} * * *"


def to_cron_expression(schedule_type: str, schedule_value: str) -> str | None:
    """返回标准 cron 表达式；interval 类型返回 None。"""
    if schedule_type == "cron":
        return normalize_cron(schedule_value)
    if schedule_type == "daily":
        return daily_to_cron(schedule_value)
    if schedule_type == "interval":
        return None
    raise ScheduleError(f"未知的调度类型：{schedule_type}")


def build_trigger(schedule_type: str, schedule_value: str, timezone_name: str):
    """构造 APScheduler trigger。"""
    if schedule_type == "interval":
        return IntervalTrigger(seconds=parse_interval(schedule_value), timezone=timezone_name)
    expr = to_cron_expression(schedule_type, schedule_value)
    parts = expr.split()
    if len(parts) == 5:
        minute, hour, day, month, dow = parts
        return CronTrigger(
            minute=minute, hour=hour, day=day, month=month, day_of_week=dow, timezone=timezone_name
        )
    second, minute, hour, day, month, dow = parts
    return CronTrigger(
        second=second,
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=dow,
        timezone=timezone_name,
    )


def next_run_times(
    schedule_type: str, schedule_value: str, timezone_name: str = "Asia/Shanghai", count: int = 3
) -> list[datetime]:
    """预览接下来的执行时间（用于前端展示）。"""
    try:
        if schedule_type == "interval":
            seconds = parse_interval(schedule_value)
            base = datetime.now(timezone.utc)
            return [base + timedelta(seconds=seconds * (i + 1)) for i in range(count)]

        expr = to_cron_expression(schedule_type, schedule_value)
        if len(expr.split()) == 5:
            expr = "0 " + expr  # croniter 支持 5 字段，但显式补秒更稳
        itr = croniter(expr, datetime.now(timezone.utc))
        return [itr.get_next(datetime) for _ in range(count)]
    except (ScheduleError, ValueError):
        return []


def describe_schedule(schedule_type: str, schedule_value: str) -> str:
    if schedule_type == "interval":
        try:
            seconds = parse_interval(schedule_value)
        except ScheduleError:
            return schedule_value
        if seconds % 86400 == 0:
            return f"每 {seconds // 86400} 天"
        if seconds % 3600 == 0:
            return f"每 {seconds // 3600} 小时"
        if seconds % 60 == 0:
            return f"每 {seconds // 60} 分钟"
        return f"每 {seconds} 秒"
    if schedule_type == "daily":
        return f"每天 {schedule_value}"
    return f"Cron: {schedule_value}"
