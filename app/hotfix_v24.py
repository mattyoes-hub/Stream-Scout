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
mp.write_text(s)

# Cards should render first. Ratings/match enrichment is secondary and must not
# stampede TMDB while the user is browsing.
jp = ROOT / 'app' / 'static' / 'app.js'
js = jp.read_text()
js = js.replace('hydrateRatings(items.slice(0,20))', 'hydrateRatings(items.slice(0,10))')
js = js.replace('hydrateMatch(items)', 'hydrateMatch(items.slice(0,10))')
jp.write_text(js)
