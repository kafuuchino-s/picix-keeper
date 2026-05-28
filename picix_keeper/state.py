"""JSON-backed local state."""

from __future__ import annotations

import json
from pathlib import Path

from .constants import DEFAULT_STATE_FILE
from .models import AppState


def load_state(path: str | Path = DEFAULT_STATE_FILE) -> AppState:
    """Load state.json or return a fresh default state."""

    state_path = Path(path)
    if not state_path.exists():
        return AppState()

    text = state_path.read_text(encoding="utf-8").strip()
    if not text:
        return AppState()

    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"{state_path} must contain a JSON object.")
    return AppState.model_validate(data)


def save_state(state: AppState, path: str | Path = DEFAULT_STATE_FILE) -> None:
    """Persist state.json with stable formatting."""

    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    data = state.model_dump(mode="json")
    data["unlocked_ids"] = sorted(data.get("unlocked_ids", []))
    state_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
