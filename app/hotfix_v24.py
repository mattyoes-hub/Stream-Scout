from pathlib import Path

ROOT = Path('/app')

# Reliability-first rollback for TMDB access. The pooled client/concurrency change
# caused production requests to pile up and time out under browser enrichment load.
tp = ROOT / 'app' / 'tmdb.py'
s = tp.read_text()
start = s.index('_client: httpx.AsyncClient | None = None')
end = s.index('\n\nasync def providers', start)
replacement = '''async def get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:\n    language = os.getenv("LANGUAGE", "en-US")\n    params = {"language": language, **(params or {})}\n    try:\n        async with httpx.AsyncClient(\n            timeout=httpx.Timeout(20.0, connect=5.0),\n            headers=_headers(),\n        ) as client:\n            res = await client.get(f"{BASE}{path}", params=params)\n    except httpx.HTTPError as e:\n        raise TMDBError(f"TMDB network error: {e}") from e\n    if res.status_code >= 400:\n        raise TMDBError(f"TMDB returned {res.status_code}: {res.text[:200]}")\n    return res.json()\n'''
s = s[:start] + replacement + s[end:]
s = s.replace('sem = asyncio.Semaphore(12)', 'sem = asyncio.Semaphore(4)')
tp.write_text(s)

# Back down enrichment concurrency in the API layer as well.
mp = ROOT / 'app' / 'main.py'
s = mp.read_text()
s = s.replace('asyncio.Semaphore(12)', 'asyncio.Semaphore(4)')
s = s.replace('payload[:20]', 'payload[:10]')

# Accept either Railway healthcheck path. /api/health remains the canonical route,
# while /health is a lightweight compatibility alias for older deployment snapshots.
if '@app.get("/health")' not in s:
    anchor = '@app.get("/api/health")'
    if anchor in s:
        s = s.replace(anchor, '@app.get("/health")\n' + anchor, 1)

# Internal card-path smoke check: perform the same TMDB sequence used by cards --
# discover, then fetch complete details for a returned title.
if '@app.get("/api/smoke_cards")' not in s:
    anchor = '@app.get("/api/search")'
    smoke = '''@app.get("/api/smoke_cards")\nasync def smoke_cards():\n    import time\n    t0 = time.perf_counter()\n    data = await tmdb.discover("movie", selected_provider_ids(), days=60, page=1)\n    rows = data.get("results", [])\n    if not rows:\n        raise HTTPException(500, "TMDB discover returned no titles")\n    item = rows[0]\n    detail = await tmdb.details("movie", int(item["id"]))\n    if not detail.get("id") or not (detail.get("title") or detail.get("name")):\n        raise HTTPException(500, "TMDB detail response was incomplete")\n    return {"ok": True, "tmdb_id": detail.get("id"), "title": detail.get("title") or detail.get("name"), "seconds": round(time.perf_counter()-t0, 3)}\n\n\n'''
    if anchor in s:
        s = s.replace(anchor, smoke + anchor, 1)
mp.write_text(s)

# Cards should render first. Ratings/match enrichment is secondary and must not
# stampede TMDB while the user is browsing.
jp = ROOT / 'app' / 'static' / 'app.js'
js = jp.read_text()
js = js.replace('hydrateRatings(items.slice(0,20))', 'hydrateRatings(items.slice(0,10))')
js = js.replace('hydrateMatch(items)', 'hydrateMatch(items.slice(0,10))')
jp.write_text(js)
