"""Telegram Bot notification helper."""

from __future__ import annotations

import requests as _requests
from loguru import logger

from .config import AppConfig
from .models import TaskStatus


def _format_status_message(status: TaskStatus) -> str:
    lines = [
        "📊 **picix-keeper 运行结果**",
        f"✅ 每日任务: {'已完成' if status.daily_done else '❌ 未完成'}",
        f"📈 月解锁进度: {status.monthly_unlock_progress}/50",
        f"📈 片单解锁进度: {status.playlist_unlock_progress}/20",
        f"💰 积分: {status.points}",
        f"📦 资源包剩余: {status.package_remaining}",
    ]
    return "\n".join(lines)


def _format_error_message(error: str) -> str:
    return f"❌ **picix-keeper 运行失败**\n{error}"


def send_telegram(config: AppConfig, message: str) -> bool:
    """Send a message via Telegram Bot API. Returns True on success."""

    tg = config.telegram
    if not tg.bot_token or not tg.chat_id:
        logger.debug("Telegram not configured (bot_token or chat_id empty); skipping notification.")
        return False

    url = f"https://api.telegram.org/bot{tg.bot_token}/sendMessage"
    payload = {
        "chat_id": tg.chat_id,
        "text": message,
        "parse_mode": "Markdown",
    }

    try:
        resp = _requests.post(url, json=payload, timeout=15)
        if resp.status_code == 200:
            logger.info("Telegram notification sent successfully.")
            return True
        logger.warning("Telegram returned HTTP {}: {}", resp.status_code, resp.text[:200])
        return False
    except Exception as exc:
        logger.warning("Failed to send Telegram notification: {}", exc)
        return False


def notify_status(config: AppConfig, status: TaskStatus) -> bool:
    """Send a formatted status report via Telegram."""
    return send_telegram(config, _format_status_message(status))


def notify_error(config: AppConfig, error: str) -> bool:
    """Send an error notification via Telegram."""
    return send_telegram(config, _format_error_message(error))
