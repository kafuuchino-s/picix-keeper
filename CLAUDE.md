# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

`picix-keeper` is a config-driven browser task runner built with Playwright. It performs a low-frequency daily "keep alive" flow on a configured website: read task-center status via user-provided CSS selectors, determine whether the daily task is complete, and optionally navigate to a configured resource and click an unlock button.

The tool does **not** guess selectors, bypass captchas, or implement anti-detection strategies. All DOM selectors and target URLs must be explicitly configured by the user in `config.yaml`.

## Tech stack

- Python 3.11+
- Playwright (sync API)
- Pydantic v2
- Typer
- loguru
- PyYAML
- setuptools (packaging)

## Development commands

Install dependencies and the package:

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .\.venv\Scripts\Activate.ps1
pip install -e .
python -m playwright install chromium
```

There is currently **no test suite, linter, or type-checker configured** in the project. Do not add one unless explicitly asked.

## CLI commands

The entry point is `picix-keeper` (defined in `pyproject.toml` as `picix_keeper.cli:app`).

- `picix-keeper init` — Create `config.yaml` (copied from `config.example.yaml`) and `state.json`.
- `picix-keeper login` — Issue a Telegram login code, bind a local ECDSA P-256 proof key, and persist token + `proof_key.pem`.
- `picix-keeper status` — Open the task center and print parsed task status.
- `picix-keeper run` — Execute the daily keep-alive flow (open task center, read status, pick resource, optionally unlock).
- `picix-keeper finalize` — Print a month-end hint based on local state (no browser involved).

All commands accept `-c/--config` to override the config file path and `-v/--verbose` for debug logging.

## Architecture and data flow

### Config system (`config.py`)

Configuration is loaded from `config.yaml` into Pydantic models (`AppConfig`, `SelectorConfig`, `ResourceUrlConfig`, etc.).

- **Selectors are user-provided placeholders.** The helper `is_placeholder_selector()` identifies strings starting with `TODO_` or containing `TODO_SELECTOR`. Null or placeholder selectors are silently skipped during status reads.
- **Paths are config-relative.** `AppConfig.resolve_path()` resolves paths relative to the directory containing `config.yaml`.
- **Strict validation.** `AppConfig` uses `extra="forbid"`; adding unexpected keys will raise a validation error.

### Request proofs (`proof.py`, `auth.py`, `http_client.py`)

picix.us requires an ECDSA P-256 signature on every authenticated API call (`X-Picix-Proof-*`). The private key is created by `picix-keeper login` (Telegram `/login` code) and stored as `proof_key.pem` next to `storage_state.json`. Replaying a browser curl token without this key revokes the session. Cloudflare `cf_clearance` is still read from `storage_state.json` when present.

### State persistence (`state.py`, `models.py`)

- `AppState` is the local JSON state (`state.json`). It tracks run cadence (`last_run_success_date` — skip further runs today only after a successful daily flow; `last_run_attempt_date` / `last_run_error` on failures), `daily_done`, counters (`monthly_unlock_progress`, `playlist_unlock_progress`, `points`, `package_remaining`), and a set of `unlocked_ids` to avoid re-unlocking the same resource. Older `state.json` files without `last_run_success_date` are migrated when loaded if `last_run_date` is today and `daily_done` is true.
- `TaskStatus` is the ephemeral status parsed from the task center page on each run.
- `state.apply_status(status)` copies the latest task-center counters into local state.

### Daily flow (`tasks.py`)

`daily_keep_alive()` is the core automation routine:

1. Check `should_run_today(state)` — skip only if `last_run_success_date == today` (failed attempts the same day do not block retries).
2. Open the task center (`config.task_center_url`) and parse status via `get_task_status(page, config)`.
3. If the daily task is already done, save state and exit.
4. Pick a resource via `resource_picker.pick_resource(config, state, prefer_playlist)`.
   - Playlist resources are preferred when `playlist_unlock_progress < PLAYLIST_UNLOCK_TARGET` (default 20).
5. If `config.dry_run` is true, log the intended action but do not click.
6. Otherwise, navigate to the resource and click the configured `unlock_button` selector.
7. Re-read task status and save state.

The flow also includes `pause_for_manual_challenge_if_needed()` at two stages (task center and resource page). If a configured challenge selector becomes visible, the script pauses and prompts the user in the terminal to complete the challenge manually before continuing.

### Resource selection (`resource_picker.py`)

Resources are configured URLs grouped into `playlist` and `normal` pools. Each resource gets a stable local ID via `sha1(url + kind)[:12]`. `pick_resource()` returns the first available resource whose ID is not already in `state.unlocked_ids`. Playlist resources are traversed first when preferred; otherwise normal resources come first.

### Scheduler helpers (`scheduler.py`)

- `should_run_today()` returns false only when `last_run_success_date` is today; network/auth/no-resource failures leave success date unset so cron can retry.
- `is_within_daily_window()` supports windows that cross midnight.
- `monthly_finalize_hint()` computes the points needed to reach the monthly 50-unlock target and the reward amount (`MONTHLY_REWARD_POINTS` = 640).

## Key files

- `picix_keeper/cli.py` — CLI entry point and command wiring.
- `picix_keeper/config.py` — Config loading, validation, and path resolution.
- `picix_keeper/tasks.py` — Daily automation routine and task-center parsing.
- `picix_keeper/browser.py` — Playwright browser session wrapper.
- `picix_keeper/models.py` — Pydantic models for state and status.
- `picix_keeper/state.py` — JSON read/write for `state.json`.
- `picix_keeper/resource_picker.py` — Resource pool building and selection.
- `picix_keeper/scheduler.py` — Run-date gating and month-end math.
- `picix_keeper/connectivity.py` — Offline detection for skipping Telegram on likely network failures.
- `picix_keeper/constants.py` — Hardcoded targets and default file paths.
- `config.example.yaml` — Default config template copied by `init`.
- `scripts/install_playwright.sh` — Convenience script to install Chromium.

