"""Run cadence and month-end hint helpers."""

from __future__ import annotations

from datetime import date

from .constants import MONTHLY_REWARD_POINTS, MONTHLY_UNLOCK_TARGET, UNLOCK_COST_POINTS
from .models import AppState, TaskStatus


def should_run_today(state: AppState) -> bool:
    """Return False only when today's run already succeeded.

    Failed attempts (network errors, expired session, no movies, etc.) do not
    set ``last_run_success_date``, so the same calendar day can retry.
    """

    return state.last_run_success_date != date.today()


def monthly_finalize_hint(status: TaskStatus) -> str:
    """Return the month-end 50-unlock calculation hint."""

    progress = max(status.monthly_unlock_progress, 0)
    missing = max(MONTHLY_UNLOCK_TARGET - progress, 0)
    needed_points = missing * UNLOCK_COST_POINTS
    return (
        f"当前月解锁进度 {progress}/{MONTHLY_UNLOCK_TARGET}，还差 {missing} 个，"
        f"需要 {needed_points} 积分，完成后可领取 {MONTHLY_REWARD_POINTS} 积分"
    )
