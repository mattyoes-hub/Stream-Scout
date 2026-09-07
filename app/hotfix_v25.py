from pathlib import Path
import re

ROOT = Path('/app')

# ---- Backend: make TMDB calls cheap enough for interactive browsing ----
tp = ROOT / 'app' / 'tmdb.py'
s = tp.read_text()

# v2.4 temporarily created a brand-new HTTP client for every TMDB call. That made
# card details and enrichment pay connection/TLS setup repeatedly. Reuse a small,
# bounded pool now that frontend request storms are fixed below.
start = s.index('async def get(path: str, params: dict[str, Any] | None = None)')
end = s.index('\n\nasync def providers', start)
replacement = '''_client: httpx.AsyncClient | None = None\n\ndef _client_instance() -> httpx.AsyncClient:\n    global _client\n    if _client is None or _client.is_closed:\n        _client = httpx.AsyncClient(\n            timeout=httpx.Timeout(10.0, connect=4.0),\n            limits=httpx.Limits(max_connections=12, max_keepalive_connections=8, keepalive_expiry=30.0),\n            headers=_headers(),\n        )\n    return _client\n\nasync def get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:\n    language = os.getenv("LANGUAGE", "en-US")\n    params = {"language": language, **(params or {})}\n    try:\n        res = await _client_instance().get(f"{BASE}{path}", params=params)\n    except httpx.HTTPError as e:\n        raise TMDBError(f"TMDB network error: {e}") from e\n    if res.status_code >= 400:\n        raise TMDBError(f"TMDB returned {res.status_code}: {res.text[:200]}")\n    return res.json()\n'''
s = s[:start] + replacement + s[end:]

# TMDB Discover already supports an exact movie certification filter. The old
# code then made up to 20 additional release-date calls to re-verify every movie,
# turning one filter change into a slow network fan-out. Keep strict verification
# only for TV, where Discover has no equivalent certification parameter.
s = s.replace(
    '    if content_rating:\n        data["results"] = await _strict_rating_filter(media_type, data.get("results", []), content_rating)\n',
    '    if content_rating and media_type == "tv":\n        data["results"] = await _strict_rating_filter(media_type, data.get("results", []), content_rating)\n'
)
tp.write_text(s)

# ---- Frontend: newest filters win, never stale results ----
jp = ROOT / 'app' / 'static' / 'app.js'
js = jp.read_text()

# Replace the discover loader with a debounced, generation-guarded version.
# Rapid filter changes used to launch overlapping requests; a slower, older
# response could arrive last and render cards that no longer matched the UI.
new_discover = r'''let streamScoutDiscoverGeneration=0;
let streamScoutDiscoverTimer=null;
function loadDiscover(){
  const generation=++streamScoutDiscoverGeneration;
  clearTimeout(streamScoutDiscoverTimer);
  return new Promise((resolve)=>{
    streamScoutDiscoverTimer=setTimeout(async()=>{
      state.mode='discover';
      $('#controls').classList.remove('hidden');
      const rental=window.streamScoutBrowseMode==='rent';
      $('#sectionEyebrow').textContent=rental?'RENTAL CATALOG':'RECENT RELEASES';
      $('#sectionTitle').textContent=rental?'Movies available to rent':`${state.mediaType==='movie'?'Movies':'TV shows'} on your services`;
      const q=new URLSearchParams({media_type:state.mediaType,days:$('#days').value,min_rating:$('#rating').value,page:state.page,sort:$('#sort').value,monetization_type:window.streamScoutBrowseMode});
      if($('#genre').value)q.set('genre_id',$('#genre').value);
      if($('#smartGenre').value)q.set('smart_genre',$('#smartGenre').value);
      if($('#contentRating').value)q.set('content_rating',$('#contentRating').value);
      if($('#runtime').value)q.set('runtime',$('#runtime').value);
      if($('#decade').value)q.set('decade',$('#decade').value);
      if(state.mediaType==='tv'&&$('#limitedSeries').checked)q.set('limited_series','true');
      updateFilterSummary();
      // Do not leave broader cards on screen while a narrower filter is pending.
      $('#grid').innerHTML='';
      $('#empty').classList.remove('hidden');
      $('#empty').innerHTML='<h3>Loading exact matches…</h3><p>Applying your selected filters.</p>';
      try{
        const d=await api('/api/discover?'+q);
        if(generation!==streamScoutDiscoverGeneration){resolve();return;}
        state.totalPages=d.total_pages;
        render(d.results);
        renderPager();
      }catch(e){
        if(generation!==streamScoutDiscoverGeneration){resolve();return;}
        state.lastResults=[];
        $('#grid').innerHTML='';
        $('#empty').classList.remove('hidden');
        $('#empty').innerHTML=`<h3>Couldn’t load titles</h3><p>${esc(e.message)}</p>`;
      }
      resolve();
    },220);
  });
}
'''
js, n = re.subn(r'async function loadDiscover\(\)\{.*?\}\nasync function loadProviders', new_discover + 'async function loadProviders', js, count=1, flags=re.S)
if n != 1:
    raise RuntimeError('Could not replace loadDiscover')

# Ratings and couple-match enrichment are useful, but they are not allowed to
# compete with the first paint or an immediate card-open request.
js = js.replace('setTimeout(()=>hydrateRatings(items.slice(0,10)),0)', 'setTimeout(()=>hydrateRatings(items.slice(0,6)),3500)')
js = js.replace('setTimeout(()=>hydrateMatch(items.slice(0,10)),0)', 'setTimeout(()=>hydrateMatch(items.slice(0,6)),5500)')

jp.write_text(js)
