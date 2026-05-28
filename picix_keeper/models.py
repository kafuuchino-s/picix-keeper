"""Pydantic models for runtime status, local state, and resources."""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ResourceKind(str, Enum):
    """Supported resource pools."""

    PLAYLIST = "playlist"
    NORMAL = "normal"


class Resource(BaseModel):
    """A candidate resource to unlock."""

    id: str
    url: str
    kind: ResourceKind


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
    daily_done: bool = False
    monthly_unlock_progress: int = 0
    playlist_unlock_progress: int = 0
    points: int = 0
    unlocked_ids: set[str] = Field(default_factory=set)
    package_remaining: int = 0

    def apply_status(self, status: TaskStatus) -> None:
        """Copy task-center counters into local state."""

        self.daily_done = status.daily_done
        self.monthly_unlock_progress = status.monthly_unlock_progress
        self.playlist_unlock_progress = status.playlist_unlock_progress
        self.points = status.points
        self.package_remaining = status.package_remaining
