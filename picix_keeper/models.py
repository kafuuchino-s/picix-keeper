"""Pydantic models for runtime status, local state, and resources."""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ResourceKind(str, Enum):
    """Supported resource pools."""

    PLAYLIST = "playlist"
    NORMAL = "normal"


class Resource(BaseModel):
    """A candidate resource to unlock."""

    id: str
    url: str
    kind: ResourceKind
    list_id: int | None = None


class TaskStatus(BaseModel):
    """Task center status parsed from the configured selectors."""

    daily_done: bool = False
    monthly_unlock_progress: int = 0
    playlist_unlock_progress: int = 0
    points: int = 0
    package_remaining: int = 0
    raw: dict[str, str] = Field(default_factory=dict)


class AppState(BaseModel):
    """Local JSON state persisted between low-frequency runs."""

    model_config = ConfigDict(validate_assignment=True)

    last_run_date: date | None = None
    # 当天流程是否已成功（站点每日任务已完成）；仅成功日跳过后续 cron/手动 run
    last_run_success_date: date | None = None
    last_run_attempt_date: date | None = None
    last_run_error: str | None = None
    daily_done: bool = False
    monthly_unlock_progress: int = 0
    playlist_unlock_progress: int = 0
    points: int = 0
    unlocked_ids: set[str] = Field(default_factory=set)
    package_remaining: int = 0

    @model_validator(mode="after")
    def _migrate_legacy_success_date(self) -> AppState:
        """Infer success date from older state.json that only had last_run_date."""

        today = date.today()
        if (
            self.last_run_success_date is None
            and self.last_run_date == today
            and self.daily_done
        ):
            self.last_run_success_date = today
        return self

    def apply_status(self, status: TaskStatus) -> None:
        """Copy task-center counters into local state."""

        self.daily_done = status.daily_done
        self.monthly_unlock_progress = status.monthly_unlock_progress
        self.playlist_unlock_progress = status.playlist_unlock_progress
        self.points = status.points
        self.package_remaining = status.package_remaining

    def mark_today_run_success(self) -> None:
        """Record that today's daily flow completed successfully."""

        today = date.today()
        self.last_run_success_date = today
        self.last_run_date = today
        self.last_run_error = None

    def record_run_failure(self, message: str) -> None:
        """Record a failed attempt today so cron/manual run can retry later."""

        self.last_run_attempt_date = date.today()
        trimmed = message.strip()
        self.last_run_error = trimmed[:500] if trimmed else None
