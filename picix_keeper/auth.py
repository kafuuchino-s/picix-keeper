"""Telegram login-code flow that registers our ECDSA proof key."""

from __future__ import annotations

import json
import time

from loguru import logger

from .config import AppConfig
from .http_client import CurlClient, proof_key_path, upsert_storage_session
from .proof import generate_private_key, public_key_spki_b64url, save_private_key

TELEGRAM_BOT = "vStreamingBot"
LOGIN_POLL_SECONDS = 10
LOGIN_TIMEOUT_SECONDS = 600


def run_telegram_login(config: AppConfig) -> None:
    """Create a proof key, issue a login code, and wait for Telegram confirmation."""

    private_key = generate_private_key()
    public_key = public_key_spki_b64url(private_key)
    client = CurlClient(config, private_key=private_key, token=None)

    base = config.base_url.rstrip("/")
    status, body = client.post(
        base + "/api/Users/getLoginCode",
        json={"proofPublicKey": public_key},
    )
    payload = json.loads(body) if status == 200 else {}
    data = payload.get("data")
    if isinstance(data, dict):
        code = str(data.get("code") or "")
    elif isinstance(data, str):
        code = data.strip()
    else:
        code = str(payload.get("code") or "")
    if status != 200 or not payload.get("success") or not code.isdigit() or len(code) != 8:
        raise RuntimeError(
            f"获取登录码失败 HTTP {status}: {payload.get('msg', body[:300])}"
        )

    deep_link = f"https://t.me/{TELEGRAM_BOT}?start=login_{code}"
    logger.info("请用 Telegram 确认登录")
    logger.info("打开: {}", deep_link)
    logger.info("或向 @{} 发送: /login {}", TELEGRAM_BOT, code)
    logger.info("等待确认，最多 {} 分钟…", LOGIN_TIMEOUT_SECONDS // 60)

    deadline = time.time() + LOGIN_TIMEOUT_SECONDS
    last_error = "超时未确认登录"
    while time.time() < deadline:
        time.sleep(LOGIN_POLL_SECONDS)
        status, body = client.post(
            base + "/api/Users/checkLoginCode",
            json={"code": code},
        )
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            last_error = f"checkLoginCode 非 JSON HTTP {status}: {body[:200]}"
            logger.debug(last_error)
            continue
        if status == 200 and payload.get("success"):
            data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
            token = data.get("token")
            session_id = data.get("sessionId")
            if token and session_id:
                key_path = proof_key_path(config)
                save_private_key(key_path, private_key)
                upsert_storage_session(config, token=token, session_id=session_id)
                logger.info("登录成功，已保存签名密钥到 {}", key_path)
                return
        err_code = str(payload.get("code") or "")
        if err_code == "LOGIN_PROOF_INVALID":
            raise RuntimeError("登录签名无效，请重新运行 picix-keeper login")
        msg = payload.get("msg") or err_code or f"HTTP {status}"
        last_error = str(msg)
        logger.debug("尚未确认: {}", last_error)

    raise RuntimeError(last_error)
