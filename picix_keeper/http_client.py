"""HTTP client backed by ``requests`` with Playwright storage_state support.

We intentionally do **not** use ``curl_cffi`` with ``impersonate`` because
``cf_clearance`` cookies are bound to the real browser's TLS fingerprint
(JA3). Any fingerprint spoofing causes Cloudflare to reject the cookie.  The
standard ``requests`` library uses the system's OpenSSL stack and is accepted
by the target backend without extra magic.
"""

from __future__ import annotations

import json
from pathlib import Path

import requests
from loguru import logger

from .config import AppConfig


class AuthenticationExpiredError(Exception):
    """Raised when Cloudflare or site cookie/token appears expired."""


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


class CurlClient:
    """Wrap ``requests.Session`` with cookie + localStorage token bootstrapping."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.session = requests.Session()
        self._token = _playwright_storage_to_tokens(
            config.resolve_path(config.storage_state_path)
        ).get("token")
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
                "Cloudflare 拦截，token 可能已过期，请重新运行 picix-keeper extract。"
            )
        if "cf-browser-verification" in text or "chk_captcha" in text:
            raise AuthenticationExpiredError(
                "检测到 Cloudflare 挑战页面，token 已过期，请重新运行 picix-keeper extract。"
            )

    def _base_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
            "referer": self.config.base_url.rstrip("/") + "/Tasks",
            "user-agent": self.config.http_client.user_agent,
        }
        if self._token:
            headers["authorization"] = self._token
        return headers

    def get(self, url: str, **kwargs) -> tuple[int, str]:
        """GET url, returning (status_code, text)."""

        logger.debug("requests GET {}", url)
        headers = {**self._base_headers(), **kwargs.pop("headers", {})}
        logger.debug("request headers: {}", headers)
        resp = self.session.get(url, headers=headers, timeout=30, **kwargs)
        self._check_cf_challenge(resp.status_code, resp.text)
        return int(resp.status_code), resp.text

    def post(self, url: str, **kwargs) -> tuple[int, str]:
        """POST url, returning (status_code, text)."""

        logger.debug("requests POST {}", url)
        headers = {**self._base_headers(), **kwargs.pop("headers", {})}
        resp = self.session.post(url, headers=headers, timeout=30, **kwargs)
        self._check_cf_challenge(resp.status_code, resp.text)
        return int(resp.status_code), resp.text
