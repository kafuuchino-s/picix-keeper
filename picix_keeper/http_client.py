"""HTTP client backed by ``requests`` with Playwright storage_state support.

We intentionally do **not** use ``curl_cffi`` with ``impersonate`` because
``cf_clearance`` cookies are bound to the real browser's TLS fingerprint
(JA3). Any fingerprint spoofing causes Cloudflare to reject the cookie.  The
standard ``requests`` library uses the system's OpenSSL stack and is accepted
by the target backend without extra magic.

Authenticated API calls also require per-request ECDSA P-256 proofs bound to
a key created during ``picix-keeper login``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from loguru import logger

from .config import AppConfig
from .proof import (
    build_proof_headers,
    load_private_key,
    request_target,
)


class AuthenticationExpiredError(Exception):
    """Raised when Cloudflare or site cookie/token appears expired."""


def proof_key_path(config: AppConfig) -> Path:
    return config.resolve_path(config.storage_state_path).with_name("proof_key.pem")


def _playwright_storage_to_tokens(path: Path) -> dict[str, str]:
    """Load localStorage tokens from Playwright storage_state.json."""

    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    tokens: dict[str, str] = {}
    for origin in data.get("origins", []):
        for item in origin.get("localStorage", []):
            name = item.get("name")
            value = item.get("value")
            if name and value is not None:
                tokens[name] = value
    return tokens


def upsert_storage_session(config: AppConfig, *, token: str, session_id: str) -> None:
    """Write token + auth-session-id into storage_state.json, keeping cookies."""

    storage_path = config.resolve_path(config.storage_state_path)
    data: dict[str, Any] = {"cookies": [], "origins": []}
    if storage_path.exists():
        try:
            loaded = json.loads(storage_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (json.JSONDecodeError, OSError):
            pass

    origin = config.base_url.rstrip("/")
    local_storage = [
        {"name": "token", "value": token},
        {"name": "auth-session-id", "value": session_id},
    ]
    origins = data.get("origins") or []
    replaced = False
    for item in origins:
        if item.get("origin") == origin:
            existing = {
                str(entry.get("name")): entry.get("value")
                for entry in item.get("localStorage") or []
                if entry.get("name")
            }
            existing["token"] = token
            existing["auth-session-id"] = session_id
            item["localStorage"] = [{"name": k, "value": v} for k, v in existing.items()]
            replaced = True
            break
    if not replaced:
        origins.append({"origin": origin, "localStorage": local_storage})
    data["origins"] = origins
    data.setdefault("cookies", [])
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    storage_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _json_body(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _api_path(url: str) -> str:
    return urlparse(url).path


class CurlClient:
    """Wrap ``requests.Session`` with cookie + localStorage token bootstrapping."""

    def __init__(
        self,
        config: AppConfig,
        *,
        private_key=None,
        token: str | None = ...,
    ) -> None:
        self.config = config
        self.session = requests.Session()
        stored = _playwright_storage_to_tokens(
            config.resolve_path(config.storage_state_path)
        )
        self._token = stored.get("token") if token is ... else token
        self._private_key = (
            private_key if private_key is not None else load_private_key(proof_key_path(config))
        )
        self._inject_cookies_from_storage()

    def _inject_cookies_from_storage(self) -> None:
        storage_path = self.config.resolve_path(self.config.storage_state_path)
        if not storage_path.exists():
            logger.debug("storage_state not found at {}", storage_path)
            return

        try:
            data = json.loads(storage_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read storage_state: {}", exc)
            return

        cookies = data.get("cookies", [])
        if not cookies:
            logger.debug("storage_state contains no cookies")
            return

        for c in cookies:
            name = c.get("name")
            value = c.get("value")
            if not name or value is None:
                continue
            domain = c.get("domain", "")
            path = c.get("path", "/")
            self.session.cookies.set(name, value, domain=domain, path=path)

        logger.debug("Injected {} cookies into requests session", len(cookies))

    def _check_cf_challenge(self, status_code: int, text: str) -> None:
        if status_code == 403:
            raise AuthenticationExpiredError(
                "Cloudflare 拦截，cookie 可能已过期，请重新运行 picix-keeper extract 更新 cf_clearance。"
            )
        if "cf-browser-verification" in text or "chk_captcha" in text:
            raise AuthenticationExpiredError(
                "检测到 Cloudflare 挑战页面，请重新运行 picix-keeper extract 更新 cf_clearance。"
            )

    def _proof_mode(self, url: str) -> str | None:
        path = _api_path(url)
        if path.endswith("/Users/getLoginCode"):
            return None
        if path.endswith("/Users/checkLoginCode"):
            return "login"
        return "session"

    def _base_headers(self, *, include_authorization: bool) -> dict[str, str]:
        headers: dict[str, str] = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
            "referer": self.config.base_url.rstrip("/") + "/Tasks",
            "user-agent": self.config.http_client.user_agent,
        }
        if include_authorization and self._token:
            headers["authorization"] = self._token
        return headers

    def _signed_headers(
        self,
        method: str,
        url: str,
        body: str,
        *,
        json_payload: Any = None,
    ) -> dict[str, str]:
        mode = self._proof_mode(url)
        include_auth = mode == "session"
        headers = self._base_headers(include_authorization=include_auth)
        if mode is None:
            return headers
        if self._private_key is None:
            raise AuthenticationExpiredError(
                "缺少浏览器签名密钥，请运行 picix-keeper login 通过 Telegram 绑定。"
            )
        if mode == "login":
            credential = str((json_payload or {}).get("code") or "")
        else:
            credential = self._token or ""
        if not credential:
            raise AuthenticationExpiredError(
                "缺少登录 token，请运行 picix-keeper login。"
            )
        headers.update(
            build_proof_headers(
                kind=mode,
                credential=credential,
                method=method,
                request_target_path=request_target(url),
                body=body,
                private_key=self._private_key,
            )
        )
        return headers

    def get(self, url: str, **kwargs) -> tuple[int, str]:
        """GET url, returning (status_code, text)."""

        extra_headers = kwargs.pop("headers", {})
        headers = {**self._signed_headers("GET", url, ""), **extra_headers}
        logger.debug("requests GET {}", url)
        logger.debug("request headers: {}", headers)
        resp = self.session.get(url, headers=headers, timeout=30, **kwargs)
        self._check_cf_challenge(resp.status_code, resp.text)
        return int(resp.status_code), resp.text

    def post(self, url: str, **kwargs) -> tuple[int, str]:
        """POST url, returning (status_code, text)."""

        extra_headers = kwargs.pop("headers", {})
        json_payload = kwargs.pop("json", None)
        body = ""
        if json_payload is not None:
            body = _json_body(json_payload)
            kwargs["data"] = body.encode("utf-8")
            extra_headers = {"content-type": "application/json", **extra_headers}
        headers = {
            **self._signed_headers("POST", url, body, json_payload=json_payload),
            **extra_headers,
        }
        logger.debug("requests POST {}", url)
        resp = self.session.post(url, headers=headers, timeout=30, **kwargs)
        self._check_cf_challenge(resp.status_code, resp.text)
        return int(resp.status_code), resp.text
