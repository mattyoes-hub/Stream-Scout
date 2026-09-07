from __future__ import annotations

import asyncio
import os
from datetime import date, timedelta
from typing import Any

import httpx

BASE = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
LOGO_BASE = "https://image.tmdb.org/t/p/w92"


class TMDBError(RuntimeError):
    pass


def _headers() -> dict[str, str]:
    token = os.getenv("TMDB_BEARER_TOKEN", "").strip()
    if not token or token == "paste_your_tmdb_read_access_token_here":
        raise TMDBError("TMDB API token is missing.")
    return {"Authorization": f"Bearer {token}", "accept": "application/json"}


_client: httpx.AsyncClient | None = None


def _client_instance() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(12.0, connect=5.0),
            limits=httpx.Limits(max_connections=40, max_keepalive_connections=20, keepalive_expiry=30.0),
            headers=_headers(),
        )
    return _client


async def get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    language = os.getenv("LANGUAGE", "en-US")
    params = {"language": language, **(params or {})}
    try:
        res = await _client_instance().get(f"{BASE}{path}", params=params)
    except httpx.HTTPError as e:
        raise TMDBError(f"TMDB network error: {e}") from e
    if res.status_code >= 400:
        raise TMDBError(f"TMDB returned {res.status_code}: {res.text[:200]}")
    return res.json()


async def providers(media_type: str) -> list[dict[str, Any]]:
    region = os.getenv("REGION", "US")
    data = await get(f"/watch/providers/{media_type}", {"watch_region": region})
    result = []
    for p in data.get("results", []):
        result.append({
            "provider_id": p["provider_id"],
            "name": p["provider_name"],
            "logo_path": p.get("logo_path"),
            "logo_url": f"{LOGO_BASE}{p['logo_path']}" if p.get("logo_path") else None,
            "display_priority": p.get("display_priority", 999),
        })
    return sorted(result, key=lambda x: (x["display_priority"], x["name"]))


async def genres(media_type: str) -> list[dict[str, Any]]:
    data = await get(f"/genre/{media_type}/list")
    return data.get("genres", [])


_keyword_cache: dict[str, int | None] = {}


async def keyword_id(name: str) -> int | None:
    key = name.strip().lower()
    if key in _keyword_cache:
        return _keyword_cache[key]
    data = await get("/search/keyword", {"query": name, "page": 1})
    rows = data.get("results", [])
    exact = next((r for r in rows if (r.get("name") or "").lower() == key), None)
    chosen = exact or (rows[0] if rows else None)
    value = chosen.get("id") if chosen else None
    _keyword_cache[key] = value
    return value


async def keyword_expression(required: list[str] | None = None, any_of: list[str] | None = None) -> str | None:
    required = required or []
    any_of = any_of or []
    required_ids, any_ids = await asyncio.gather(
        asyncio.gather(*(keyword_id(x) for x in required)) if required else asyncio.sleep(0, result=[]),
        asyncio.gather(*(keyword_id(x) for x in any_of)) if any_of else asyncio.sleep(0, result=[]),
    )
    required_ids = [x for x in required_ids if x]
    any_ids = [x for x in any_ids if x]
    parts: list[str] = []
    if required_ids:
        parts.append(",".join(str(x) for x in required_ids))
    if any_ids:
        parts.append("|".join(str(x) for x in any_ids))
    return ",".join(parts) if parts else None


async def _strict_rating_filter(media_type: str, items: list[dict[str, Any]], wanted: str) -> list[dict[str, Any]]:
    """Verify the actual US certification for every result. Never silently relax a user-selected rating."""
    sem = asyncio.Semaphore(12)

    async def check(item: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        async with sem:
            try:
                return item, await content_rating_for(media_type, int(item["id"]))
            except Exception:
                return item, None

    checked = await asyncio.gather(*(check(item) for item in items))
    return [item for item, rating in checked if rating == wanted]


async def discover(
    media_type: str,
    provider_ids: list[int],
    days: int = 60,
    genre_id: int | None = None,
    min_rating: float = 0,
    page: int = 1,
    sort_by: str = "popularity.desc",
    content_rating: str | None = None,
    keyword_required: list[str] | None = None,
    keyword_any: list[str] | None = None,
    runtime: str | None = None,
    decade: int | None = None,
    monetization_type: str = "subscription",
) -> dict[str, Any]:
    region = os.getenv("REGION", "US")
    today = date.today()
    start = today - timedelta(days=max(1, min(days, 3650))) if days > 0 else None

    monetization = "rent" if monetization_type == "rent" else "flatrate|free|ads"
    params: dict[str, Any] = {
        "watch_region": region,
        "with_watch_monetization_types": monetization,
        "include_adult": "false",
        "page": page,
        "sort_by": sort_by,
        "vote_average.gte": min_rating,
        "vote_count.gte": 10 if min_rating else 0,
        "with_original_language": "en",
    }
    if provider_ids:
        params["with_watch_providers"] = "|".join(str(x) for x in provider_ids)
    if genre_id:
        params["with_genres"] = genre_id
    if runtime == "under90":
        params["with_runtime.lte"] = 89
    elif runtime == "90to120":
        params["with_runtime.gte"] = 90
        params["with_runtime.lte"] = 120
    elif runtime == "over120":
        params["with_runtime.gte"] = 121
    kw = await keyword_expression(keyword_required, keyword_any)
    if kw:
        params["with_keywords"] = kw

    if media_type == "movie":
        if decade:
            params["primary_release_date.gte"] = f"{decade}-01-01"
            params["primary_release_date.lte"] = f"{decade+9}-12-31"
        else:
            if start:
                params["primary_release_date.gte"] = start.isoformat()
            params["primary_release_date.lte"] = today.isoformat()
        if content_rating:
            # Keep TMDB's server-side certification narrowing, then strictly verify below.
            params["certification_country"] = region
            params["certification"] = content_rating
        data = await get("/discover/movie", params)
    else:
        if decade:
            params["first_air_date.gte"] = f"{decade}-01-01"
            params["first_air_date.lte"] = f"{decade+9}-12-31"
        else:
            if start:
                params["first_air_date.gte"] = start.isoformat()
            params["first_air_date.lte"] = today.isoformat()
        data = await get("/discover/tv", params)

    if content_rating:
        data["results"] = await _strict_rating_filter(media_type, data.get("results", []), content_rating)
    return data


async def search(query: str, page: int = 1) -> dict[str, Any]:
    data = await get("/search/multi", {"query": query, "page": page, "include_adult": "false"})
    data["results"] = [x for x in data.get("results", []) if x.get("media_type") in {"movie", "tv"} and x.get("original_language") == "en"]
    return data


async def details(media_type: str, tmdb_id: int) -> dict[str, Any]:
    extra = "release_dates" if media_type == "movie" else "content_ratings"
    data = await get(f"/{media_type}/{tmdb_id}", {"append_to_response": f"videos,watch/providers,external_ids,{extra}"})
    data["media_type"] = media_type
    return data


async def rental_providers_for(media_type: str, tmdb_id: int) -> list[dict[str, Any]]:
    region = os.getenv("REGION", "US")
    data = await get(f"/{media_type}/{tmdb_id}/watch/providers")
    rows = data.get("results", {}).get(region, {}).get("rent", [])
    return [
        {
            "id": p.get("provider_id"),
            "name": p.get("provider_name"),
            "logo_url": f"{LOGO_BASE}{p['logo_path']}" if p.get("logo_path") else None,
        }
        for p in rows
    ]


def image(path: str | None) -> str | None:
    return f"{IMAGE_BASE}{path}" if path else None


def trailer_url(videos: dict[str, Any] | None) -> str | None:
    if not videos:
        return None
    candidates = videos.get("results", [])
    preferred = next((v for v in candidates if v.get("site") == "YouTube" and v.get("type") == "Trailer" and v.get("official")), None)
    preferred = preferred or next((v for v in candidates if v.get("site") == "YouTube" and v.get("type") == "Trailer"), None)
    return f"https://www.youtube.com/watch?v={preferred['key']}" if preferred else None


def _us_rating_from_blob(media_type: str, data: dict[str, Any]) -> str | None:
    region = os.getenv("REGION", "US")
    if media_type == "tv":
        for row in data.get("content_ratings", {}).get("results", []):
            if row.get("iso_3166_1") == region and row.get("rating"):
                return row["rating"]
        return None
    for country in data.get("release_dates", {}).get("results", []):
        if country.get("iso_3166_1") != region:
            continue
        rows = country.get("release_dates", [])
        rows = sorted(rows, key=lambda r: 0 if r.get("type") in {3, 4, 6} else 1)
        for row in rows:
            if row.get("certification"):
                return row["certification"]
    return None


async def content_rating_for(media_type: str, tmdb_id: int) -> str | None:
    if media_type == "tv":
        data = await get(f"/tv/{tmdb_id}/content_ratings")
        return _us_rating_from_blob("tv", {"content_ratings": data})
    data = await get(f"/movie/{tmdb_id}/release_dates")
    return _us_rating_from_blob("movie", {"release_dates": data})


def content_rating_from_details(media_type: str, data: dict[str, Any]) -> str | None:
    return _us_rating_from_blob(media_type, data)


async def upcoming(media_type: str, days_ahead: int = 90, page: int = 1) -> dict[str, Any]:
    today = date.today()
    end = today + timedelta(days=max(1, min(days_ahead, 365)))
    params: dict[str, Any] = {
        "include_adult": "false",
        "page": page,
        "sort_by": "primary_release_date.asc" if media_type == "movie" else "first_air_date.asc",
        "with_original_language": "en",
        "vote_count.gte": 0,
    }
    if media_type == "movie":
        params["primary_release_date.gte"] = today.isoformat()
        params["primary_release_date.lte"] = end.isoformat()
        return await get("/discover/movie", params)
    params["first_air_date.gte"] = today.isoformat()
    params["first_air_date.lte"] = end.isoformat()
    return await get("/discover/tv", params)
