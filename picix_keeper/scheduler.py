"""Run cadence and month-end hint helpers."""

from __future__ import annotations

from datetime import date, datetime

from .config import AppConfig
from .constants import MONTHLY_REWARD_POINTS, MONTHLY_UNLOCK_TARGET, UNLOCK_COST_POINTS
from .models import AppState, TaskStatus


def should_run_today(state: AppState) -> bool:
    """Return False only when today's daily flow has already completed."""

    return not (state.last_run_date == date.today() and state.daily_done)


def is_within_daily_window(config: AppConfig, now: datetime | None = None) -> bool:
    """Check the preferred run window, supporting windows that cross midnight."""

    if config.daily_run_window.start is None or config.daily_run_window.end is None:
        return True

    current = (now or datetime.now()).time()
    start = config.daily_run_window.start
    end = config.daily_run_window.end
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def monthly_finalize_hint(status: TaskStatus) -> str:
    """Return the month-end 50-unlock calculation hint."""

    progress = max(status.monthly_unlock_progress, 0)
    missing = max(MONTHLY_UNLOCK_TARGET - progress, 0)
    needed_points = missing * UNLOCK_COST_POINTS
    return (
        f"当前月解锁进度 {progress}/{MONTHLY_UNLOCK_TARGET}，还差 {missing} 个，"
        f"需要 {needed_points} 积分，完成后可领取 {MONTHLY_REWARD_POINTS} 积分"
    )
