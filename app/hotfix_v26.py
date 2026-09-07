from pathlib import Path
import re

ROOT = Path('/app')

# ---- Backend: make rental browsing cheap and make detail "where to watch" useful ----
mp = ROOT / 'app' / 'main.py'
s = mp.read_text()
s = re.sub(r'BUILD_VERSION = "[^"]+"', 'BUILD_VERSION = "2.6.1-cloud"', s, count=1)

# Rental Discover is already filtered by TMDB's rent monetization type. Do not make
# one extra watch-provider request per card before the grid can render. Provider
# names are fetched when the user opens a title instead.
start = s.find('    if monetization_type == "rent" and results:')
if start != -1:
    end = s.find('    return {"page":', start)
    if end == -1:
        raise RuntimeError('Could not locate rental discover return block')
    s = s[:start] + s[end:]

# The existing detail UI already renders the `providers` list as Where to Watch.
# Include rental providers in that same list, while preserving the separate
# rental_providers field added by v2.4 for future UI use.
old = '    provider_rows = provider_blob.get("flatrate", []) + provider_blob.get("free", []) + provider_blob.get("ads", [])\n'
new = '    provider_rows = provider_blob.get("flatrate", []) + provider_blob.get("free", []) + provider_blob.get("ads", []) + provider_blob.get("rent", [])\n'
if old in s:
    s = s.replace(old, new, 1)

mp.write_text(s)

# ---- TMDB: short-lived response cache + persistent keep-alive client ----
tp = ROOT / 'app' / 'tmdb.py'
t = tp.read_text()
if 'import time\n' not in t:
    t = t.replace('import os\n', 'import os\nimport time\n', 1)

if '_response_cache:' not in t:
    anchor = 'class TMDBError(RuntimeError):\n    pass\n'
    cache_defs = '''class TMDBError(RuntimeError):\n    pass\n\n\n_response_cache: dict[tuple[str, tuple[tuple[str, str], ...]], tuple[float, dict[str, Any]]] = {}\n_CACHE_TTL_SECONDS = 900.0\n_CACHE_MAX_ITEMS = 512\n'''
    if anchor not in t:
        raise RuntimeError('Could not locate TMDBError cache anchor')
    t = t.replace(anchor, cache_defs, 1)

get_start = t.index('async def get(path: str, params: dict[str, Any] | None = None)')
get_end = t.index('\n\nasync def providers', get_start)
get_impl = '''async def get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:\n    language = os.getenv("LANGUAGE", "en-US")\n    params = {"language": language, **(params or {})}\n    key = (path, tuple(sorted((str(k), str(v)) for k, v in params.items())))\n    now = time.monotonic()\n    cached = _response_cache.get(key)\n    if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:\n        return cached[1]\n    try:\n        res = await _client_instance().get(f"{BASE}{path}", params=params)\n    except httpx.HTTPError as e:\n        raise TMDBError(f"TMDB network error: {e}") from e\n    if res.status_code >= 400:\n        raise TMDBError(f"TMDB returned {res.status_code}: {res.text[:200]}")\n    data = res.json()\n    if len(_response_cache) >= _CACHE_MAX_ITEMS:\n        _response_cache.clear()\n    _response_cache[key] = (now, data)\n    return data\n'''
t = t[:get_start] + get_impl + t[get_end:]
tp.write_text(t)
