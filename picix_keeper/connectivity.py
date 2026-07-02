"""Detect likely offline / no-network failures (skip Telegram in those cases)."""

from __future__ import annotations

from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import Timeout as RequestsTimeout

# Windows: network unreachable / host down / connection reset / timed out
_WIN_OFFLINE_ERRNOS = frozenset({10051, 10052, 10053, 10054, 10060, 10061})
# POSIX-ish
_UNIX_OFFLINE_ERRNOS = frozenset({101, 110, 111, 113})


def _is_offline_leaf(exc: BaseException) -> bool:
    if isinstance(exc, (RequestsConnectionError, RequestsTimeout)):
        return True
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, OSError):
        errno = getattr(exc, "errno", None)
        if errno in _WIN_OFFLINE_ERRNOS or errno in _UNIX_OFFLINE_ERRNOS:
            return True
        text = str(exc).lower()
        if "getaddrinfo" in text or "name or service not known" in text:
            return True
        if "network is unreachable" in text or "no route to host" in text:
            return True
    return False


def is_likely_offline(exc: BaseException) -> bool:
    """True when failure is probably due to no network (Telegram would fail too)."""

    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if _is_offline_leaf(current):
            return True
        current = current.__cause__ or current.__context__
    return False