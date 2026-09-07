from __future__ import annotations

import os
from typing import Any
import httpx

BASE = "https://www.omdbapi.com/"


def configured() -> bool:
    key = os.getenv("OMDB_API_KEY", "").strip()
    return bool(key) and key != "paste_your_omdb_api_key_here"


def _parse(data: dict[str, Any]) -> dict[str, Any]:
    rt_score = None
    for rating in data.get("Ratings", []):
        if rating.get("Source") == "Rotten Tomatoes":
            rt_score = rating.get("Value")
            break
    imdb_score = data.get("imdbRating")
    if imdb_score in {None, "", "N/A"}:
        imdb_score = None
    metacritic = data.get("Metascore")
    if metacritic in {None, "", "N/A"}:
        metacritic = None
    return {
        "imdb_score": imdb_score,
        "rt_score": rt_score,
        "metacritic_score": metacritic,
        "imdb_id": data.get("imdbID"),
        "source_title": data.get("Title"),
        "source_year": data.get("Year"),
    }


async def lookup(imdb_id: str | None = None, title: str | None = None, year: str | None = None, media_type: str | None = None) -> dict[str, Any]:
    if not configured():
        return {"ok": False, "status": "not_configured", "error": "OMDb API key is not configured."}
    params: dict[str, Any] = {"apikey": os.getenv("OMDB_API_KEY", "").strip(), "r": "json", "plot": "short"}
    if imdb_id:
        params["i"] = imdb_id
    elif title:
        params["t"] = title
        if year:
            params["y"] = str(year)[:4]
        if media_type:
            params["type"] = "movie" if media_type == "movie" else "series"
    else:
        return {"ok": False, "status": "no_identifier", "error": "No IMDb ID or title available."}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(BASE, params=params)
    except Exception as e:
        return {"ok": False, "status": "network_error", "error": str(e)}
    if r.status_code >= 400:
        return {"ok": False, "status": "http_error", "error": f"OMDb returned HTTP {r.status_code}."}
    try:
        data = r.json()
    except Exception:
        return {"ok": False, "status": "bad_response", "error": "OMDb returned an unreadable response."}
    if data.get("Response") == "False":
        err = data.get("Error") or "OMDb could not find this title."
        low = err.lower()
        status = "key_error" if ("invalid api key" in low or "api key" in low or "request limit" in low) else "not_found"
        return {"ok": False, "status": status, "error": err, "raw": data}
    parsed = _parse(data)
    return {"ok": True, "status": "ok", **parsed, "data": data}


async def ratings(imdb_id: str | None, title: str | None = None, year: str | None = None, media_type: str | None = None) -> dict[str, Any]:
    primary = await lookup(imdb_id=imdb_id, title=title, year=year, media_type=media_type)
    needs_fallback = title and (
        not primary.get("ok") or
        (not primary.get("rt_score") and not primary.get("imdb_score"))
    )
    if needs_fallback:
        fallback = await lookup(title=title, year=year, media_type=media_type)
        if fallback.get("ok") and (fallback.get("rt_score") or fallback.get("imdb_score")):
            return fallback
    return primary


async def test_key() -> dict[str, Any]:
    return await lookup(imdb_id="tt0133093")
