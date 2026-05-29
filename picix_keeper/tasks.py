"""Daily task flow and task-center parsing — pure HTTP."""

from __future__ import annotations

import json as _json
import re
from datetime import date
from typing import Any

from loguru import logger

from .config import AppConfig
from .constants import PLAYLIST_UNLOCK_TARGET
from .http_client import AuthenticationExpiredError, CurlClient
from .models import AppState, TaskStatus
from .resource_picker import pick_resource
from .scheduler import should_run_today
from .state import save_state


DONE_KEYWORDS = ("已完成", "完成", "done", "completed", "finished", "true", "yes")


def _parse_first_int(text: str | None, default: int = 0) -> int:
    if not text:
        return default
    match = re.search(r"\d+", text.replace(",", ""))
    if match is None:
        return default
    return int(match.group(0))


def _parse_done(text: str | None) -> bool:
    if not text:
        return False
    normalized = text.strip().lower()
    return any(keyword in normalized for keyword in DONE_KEYWORDS)


def is_daily_done(status: TaskStatus) -> bool:
    """Return whether the parsed daily task is done."""
    return status.daily_done


def _save_status_to_state(status: TaskStatus, state: AppState, config: AppConfig) -> None:
    state.apply_status(status)
    if status.daily_done:
        state.last_run_date = date.today()
    save_state(state, config.resolve_path(config.state_file))


# ---------------------------------------------------------------------------
# JSON API helpers
# ---------------------------------------------------------------------------

def _parse_task_list_json(body: str) -> dict[str, Any]:
    """Parse /api/Tasks/list JSON and return extracted fields."""
    data: dict[str, Any] = {}
    try:
        data = _json.loads(body)
    except _json.JSONDecodeError as exc:
        raise AuthenticationExpiredError(f"任务列表 JSON 解析失败: {exc}") from exc

    tasks = data.get("data", [])
    out: dict[str, Any] = {
        "daily_done": False,
        "daily_accepted": False,
        "monthly_unlock_progress": 0,
        "playlist_unlock_progress": 0,
    }
    for t in tasks:
        if not isinstance(t, dict):
            continue
        unique = t.get("unique", "")
        proc = t.get("process", {}) or {}
        if unique == "D_UL_1":
            out["daily_done"] = (proc.get("isFinish") == "Y")
            out["daily_accepted"] = bool(proc)  # has process ⇒ already accepted
        elif unique == "M_UL_50":
            out["monthly_unlock_progress"] = proc.get("process", 0)
        elif unique == "M_UL_ML_20":
            out["playlist_unlock_progress"] = proc.get("process", 0)
    return out


def get_task_status_via_http(config: AppConfig) -> TaskStatus:
    """Fetch task center via HTTP using site JSON APIs."""

    client = CurlClient(config)
    base = config.base_url.rstrip("/")

    # 1) Task list
    status_code, body = client.get(base + "/api/Tasks/list")
    if status_code != 200:
        raise AuthenticationExpiredError(
            f"任务列表返回 HTTP {status_code}，cookie/token 可能已过期，请重新运行 picix-keeper extract。"
        )
    parsed = _parse_task_list_json(body)

    # 2) Package remaining
    package_remaining = 0
    try:
        sc2, body2 = client.get(base + "/api/Packages/listMine")
        if sc2 == 200:
            pkg_data = _json.loads(body2).get("data", [])
            if pkg_data:
                p = pkg_data[0]
                package_remaining = p.get("total", 0) - p.get("used", 0)
                logger.debug("Package: total={}, used={}, remaining={}", p.get("total"), p.get("used"), package_remaining)
    except Exception as exc:
        logger.debug("Package fetch failed: {}", exc)

    # 3) Points
    points = 0
    try:
        sc3, body3 = client.get(base + "/api/Users/listPointHistory")
        if sc3 == 200:
            hist = _json.loads(body3).get("data", [])
            if hist:
                points = hist[0].get("totalPoints", 0)
                logger.debug("Points: totalPoints={}", points)
    except Exception as exc:
        logger.debug("PointHistory fetch failed: {}", exc)

    return TaskStatus(
        daily_done=parsed["daily_done"],
        monthly_unlock_progress=int(parsed["monthly_unlock_progress"]),
        playlist_unlock_progress=int(parsed["playlist_unlock_progress"]),
        points=points,
        package_remaining=package_remaining,
        raw={"api_response": body[:2000]},
    )


# ---------------------------------------------------------------------------
# Auto-buy resource pack
# ---------------------------------------------------------------------------

def _get_package_remaining(client: CurlClient, base: str) -> int:
    """Return remaining unlock quota across all owned packages."""
    sc, body = client.get(base + "/api/Packages/listMine")
    if sc != 200:
        return 0
    pkgs = _json.loads(body).get("data", [])
    return sum(p.get("total", 0) - p.get("used", 0) for p in pkgs)


def _get_points(client: CurlClient, base: str) -> int:
    """Return current total points."""
    sc, body = client.get(base + "/api/Users/listPointHistory")
    if sc != 200:
        return 0
    hist = _json.loads(body).get("data", [])
    return hist[0].get("totalPoints", 0) if hist else 0


def _buy_package(client: CurlClient, base: str, good_id: int) -> bool:
    """POST /Malls/payGood to buy a resource pack. Returns True on success."""
    sc, body = client.post(base + "/api/Malls/payGood", json={"goodId": good_id})
    resp = _json.loads(body) if sc == 200 else {}
    if resp.get("success"):
        logger.info("✅ 购买资源包 goodId={} 成功", good_id)
        return True
    logger.warning("购买资源包失败: {}", resp.get("msg", body[:200]))
    return False


def _ensure_package_quota(config: AppConfig, client: CurlClient, base: str) -> None:
    """Check package quota; auto-buy if configured and quota is 0."""
    remaining = _get_package_remaining(client, base)
    logger.info("📦 资源包剩余: {} 次", remaining)
    if remaining > 0:
        return

    if not config.auto_buy.enabled:
        raise RuntimeError(
            f"资源包已用完（剩余 {remaining} 次），auto_buy 未启用，无法继续解锁。"
        )

    points = _get_points(client, base)
    # goodId 1 = 轻量包(450分), 2 = 标准包(1000分), 3 = 增强包(1600分)
    prices = {1: 450, 2: 1000, 3: 1600}
    good_id = config.auto_buy.good_id
    price = prices.get(good_id, 450)

    if points < price:
        raise RuntimeError(
            f"资源包已用完，积分 {points} 不够购买资源包（需要 {price} 积分）。"
        )

    logger.info("积分 {} 足够，自动购买资源包 goodId={} ({} 积分)", points, good_id, price)
    if not _buy_package(client, base, good_id):
        raise RuntimeError("自动购买资源包失败，无法继续。")


# ---------------------------------------------------------------------------
# Task accept / finish
# ---------------------------------------------------------------------------

def _accept_daily_task(client: CurlClient, base: str) -> None:
    """POST /Tasks/accept to claim the daily unlock task."""
    sc, body = client.post(base + "/api/Tasks/accept", json={"unique": "D_UL_1"})
    resp = _json.loads(body) if sc == 200 else {}
    if resp.get("success"):
        logger.info("✅ 每日解锁任务领取成功")
    else:
        # "周期内您已接取过该任务" is fine — task already accepted
        msg = resp.get("msg", "")
        if "已接取" in msg:
            logger.info("每日解锁任务已领取过（无需重复领取）")
        else:
            logger.warning("领取任务返回: {}", msg)


def _finish_daily_task(client: CurlClient, base: str) -> None:
    """POST /Tasks/finish to collect the daily task reward (15 points)."""
    sc, body = client.post(base + "/api/Tasks/finish", json={"unique": "D_UL_1"})
    resp = _json.loads(body) if sc == 200 else {}
    if resp.get("success"):
        logger.info("✅ 每日解锁任务完成，已领取 15 积分")
    else:
        msg = resp.get("msg", "")
        if "已经完成" in msg:
            logger.info("每日解锁任务已完成过（无需重复领取积分）")
        else:
            logger.warning("完成任务返回: {}", msg)


# ---------------------------------------------------------------------------
# Unlock resource (stub — waiting for unlock API endpoint)
# ---------------------------------------------------------------------------

def unlock_resource_via_http(config: AppConfig, movie_id: str) -> None:
    """POST /Movies/unlock to unlock a movie using resource pack quota."""
    client = CurlClient(config)
    base = config.base_url.rstrip("/")

    sc, body = client.post(base + "/api/Movies/unlock", json={"movieId": int(movie_id)})
    resp = _json.loads(body) if sc == 200 else {}
    if resp.get("success"):
        logger.info("🔓 影片 id={} 解锁成功", movie_id)
    else:
        msg = resp.get("msg", body[:200])
        raise RuntimeError(f"影片 id={movie_id} 解锁失败: {msg}")


# ---------------------------------------------------------------------------
# Main daily flow
# ---------------------------------------------------------------------------

def daily_keep_alive_http(config: AppConfig, state: AppState) -> AppState:
    """Run the daily flow: accept task → unlock movie → finish task."""

    if not should_run_today(state):
        logger.info("Today's daily flow is already marked complete; exiting.")
        return state

    # Step 0: check current status
    status = get_task_status_via_http(config)
    if is_daily_done(status):
        logger.info("Task center reports daily task already complete.")
        _save_status_to_state(status, state, config)
        return state

    client = CurlClient(config)
    base = config.base_url.rstrip("/")

    # Step 1: accept daily task (if not yet accepted)
    if not _parse_task_list_json(
        client.get(base + "/api/Tasks/list")[1]
    ).get("daily_accepted"):
        _accept_daily_task(client, base)

    # Step 2: ensure package quota (auto-buy if needed)
    _ensure_package_quota(config, client, base)

    # Step 3: pick and unlock a movie
    prefer_playlist = status.playlist_unlock_progress < PLAYLIST_UNLOCK_TARGET
    resource = pick_resource(config, prefer_playlist=prefer_playlist)
    if resource is None:
        logger.warning("没有未解锁的影片可供选择，无法完成每日任务。")
        _save_status_to_state(status, state, config)
        return state

    if config.dry_run:
        logger.info(
            "dry-run: 会解锁影片 id={} ({})",
            resource.id,
            resource.url,
        )
        _save_status_to_state(status, state, config)
        return state

    unlock_resource_via_http(config, resource.id)

    # Step 4: finish daily task (claim reward)
    _finish_daily_task(client, base)

    # Step 5: re-read status and save
    updated_status = get_task_status_via_http(config)
    _save_status_to_state(updated_status, state, config)
    return state
