"""Resource selection helpers — API-driven favorite lists."""

from __future__ import annotations

import json as _json

from loguru import logger

from .config import AppConfig
from .http_client import CurlClient
from .models import Resource, ResourceKind


def _resolve_favorite_list_ids(config: AppConfig) -> list[int]:
    """Return favorite list IDs to scan.

    If ``favorite_list_ids`` is explicitly configured, use it.
    Otherwise, auto-discover all favorite lists via
    ``/api/Movies/listMyMovieList``.
    """

    if config.resource_urls.favorite_list_ids:
        return config.resource_urls.favorite_list_ids

    # Auto-discover: fetch all favorite lists from the API
    client = CurlClient(config)
    base = config.base_url.rstrip("/")
    try:
        status_code, body = client.get(base + "/api/Movies/listMyMovieList")
        if status_code != 200:
            logger.warning("listMyMovieList returned HTTP {}", status_code)
            return []
        data = _json.loads(body).get("data") or {}
        # The key was renamed from ``favorite`` to ``mine``; accept both.
        fav_lists = data.get("mine") or data.get("favorite") or []
        ids = [fl["id"] for fl in fav_lists if isinstance(fl, dict) and "id" in fl]
        logger.info("Auto-discovered {} favorite list(s): {}", len(ids), ids)
        return ids
    except Exception as exc:
        logger.warning("Failed to auto-discover favorite lists: {}", exc)
        return []


def fetch_favorite_list_resources(config: AppConfig) -> list[Resource]:
    """Fetch unlocked movies from favorite lists via API.

    Only movies with ``isUnlock: false`` are returned — the server-side
    status is the single source of truth.
    """

    list_ids = _resolve_favorite_list_ids(config)
    if not list_ids:
        return []

    client = CurlClient(config)
    resources: list[Resource] = []
    base = config.base_url.rstrip("/")
    for list_id in list_ids:
        api_url = base + f"/api/Movies/getMovieList?listId={list_id}"
        try:
            status_code, body = client.get(api_url)
            if status_code != 200:
                logger.warning("Favorite list {} returned HTTP {}", list_id, status_code)
                continue
            data = _json.loads(body).get("data", {})
            for movie in data.get("list", []):
                if movie.get("isUnlock"):
                    continue
                movie_list_link_id = movie.get("movieListLinkId")
                if (
                    not isinstance(movie_id, int)
                    or not isinstance(movie_list_link_id, int)
                    or movie_id <= 0
                    or movie_list_link_id <= 0
                ):
                    continue
                resources.append(
                    Resource(
                        id=str(movie_id),
                        url=f"{base}/Movies/Detail/{movie_id}",
                        kind=ResourceKind.PLAYLIST,
                        movie_list_link_id=movie_list_link_id,
                    )
                )
        except Exception as exc:
            logger.warning("Failed to fetch favorite list {}: {}", list_id, exc)
    return resources


def pick_resource(
    config: AppConfig,
    *,
    prefer_playlist: bool = True,
) -> Resource | None:
    """Pick the next unlocked movie from favorite lists.

    The API already filters out unlocked movies (``isUnlock: true``),
    so the first available item is simply returned.  Falls back to
    manually configured ``playlist`` / ``normal`` URLs if no favorite
    list movies are found.
    """

    # 1) Favorite list movies (API-driven, already filtered by isUnlock)
    favorite = fetch_favorite_list_resources(config)
    if favorite:
        return favorite[0]

    # 2) Manual URL fallback (legacy)
    from hashlib import sha1

    for urls, kind in [
        (config.resource_urls.playlist, ResourceKind.PLAYLIST),
        (config.resource_urls.normal, ResourceKind.NORMAL),
    ]:
        for url in urls:
            rid = f"{kind.value}:{sha1(url.strip().encode()).hexdigest()[:12]}"
            return Resource(id=rid, url=url, kind=kind)

    return None
