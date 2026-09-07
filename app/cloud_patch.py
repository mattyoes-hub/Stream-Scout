from __future__ import annotations

from pathlib import Path
import re

ROOT = Path('/app')


def patch_main() -> None:
    p = ROOT / 'app' / 'main.py'
    s = p.read_text()
    s = s.replace('app = FastAPI(title="Stream Scout", version="2.3.0", lifespan=lifespan)', 'app = FastAPI(title="Stream Scout", version="2.4.0", lifespan=lifespan)')
    s = re.sub(r'BUILD_VERSION = "[^"]+"', 'BUILD_VERSION = "2.4.0-cloud"', s, count=1)

    selected_fn = '''def selected_provider_ids() -> list[int]:\n    return [r["provider_id"] for r in db.rows("SELECT provider_id FROM providers WHERE selected=1 ORDER BY display_priority")]\n'''
    if 'def rental_provider_ids()' not in s and selected_fn in s:
        s = s.replace(selected_fn, selected_fn + '''\n\ndef rental_provider_ids() -> list[int]:\n    preferred = {"apple tv store", "amazon video", "fandango at home", "google play movies", "youtube"}\n    rows = db.rows("SELECT provider_id,name FROM providers ORDER BY display_priority,name")\n    ids = [int(r["provider_id"]) for r in rows if (r.get("name") or "").strip().lower() in preferred]\n    return ids or [2, 3, 7, 10, 192]\n''')

    start = s.index('@app.get("/api/discover")')
    end = s.index('@app.get("/api/search")', start)
    block = s[start:end]
    if 'monetization_type:' not in block:
        block = block.replace('    limited_series: bool = False,\n):', '    limited_series: bool = False,\n    monetization_type: str = Query("subscription", pattern="^(subscription|rent)$"),\n):')
    block = block.replace('            media_type, selected_provider_ids(), days, effective_genre, min_rating, page,', '            media_type, (rental_provider_ids() if monetization_type == "rent" else selected_provider_ids()), days, effective_genre, min_rating, page,')
    block = block.replace('            decade=decade,\n        )', '            decade=decade,\n            monetization_type=monetization_type,\n        )')
    old_tail = '''    results = [normalize(x, media_type, lib) for x in raw_results]\n    results = [x for x in results if not x["hidden"]]\n    return {"page": data.get("page", 1), "total_pages": min(data.get("total_pages", 1), 20), "results": results}\n'''
    new_tail = '''    results = [normalize(x, media_type, lib) for x in raw_results]\n    results = [x for x in results if not x["hidden"]]\n    if monetization_type == "rent" and results:\n        sem = asyncio.Semaphore(12)\n        async def rent_rows(item):\n            async with sem:\n                try:\n                    return await tmdb.rental_providers_for(media_type, int(item["id"]))\n                except Exception:\n                    return []\n        rentals = await asyncio.gather(*(rent_rows(item) for item in results))\n        for item, providers in zip(results, rentals):\n            item["rental_providers"] = providers\n        results = [item for item in results if item.get("rental_providers")]\n    return {"page": data.get("page", 1), "total_pages": min(data.get("total_pages", 1), 20), "results": results, "monetization_type": monetization_type}\n'''
    if old_tail in block:
        block = block.replace(old_tail, new_tail)
    s = s[:start] + block + s[end:]

    # Faster enrichment batches: keep initial cards non-blocking and resolve visible ratings concurrently.
    s = s.replace('payload[:40]', 'payload[:20]')
    s = s.replace('sem = asyncio.Semaphore(6)', 'sem = asyncio.Semaphore(12)')

    # Detail response should distinguish subscription availability from rental availability.
    marker = '''    provider_rows = provider_blob.get("flatrate", []) + provider_blob.get("free", []) + provider_blob.get("ads", [])\n    seen = set()\n    provider_rows = [p for p in provider_rows if not (p["provider_id"] in seen or seen.add(p["provider_id"]))]\n'''
    if marker in s and 'rental_provider_rows = provider_blob.get("rent"' not in s:
        s = s.replace(marker, marker + '''    rental_provider_rows = provider_blob.get("rent", [])\n    rent_seen = set()\n    rental_provider_rows = [p for p in rental_provider_rows if not (p["provider_id"] in rent_seen or rent_seen.add(p["provider_id"]))]\n''')
    provider_return = '''        "providers": [{"id": p["provider_id"], "name": p["provider_name"], "logo_url": f"https://image.tmdb.org/t/p/w92{p['logo_path']}" if p.get("logo_path") else None} for p in provider_rows],\n'''
    if provider_return in s and '"rental_providers":' not in s:
        s = s.replace(provider_return, provider_return + '''        "rental_providers": [{"id": p["provider_id"], "name": p["provider_name"], "logo_url": f"https://image.tmdb.org/t/p/w92{p['logo_path']}" if p.get("logo_path") else None} for p in rental_provider_rows],\n''')

    p.write_text(s)


def patch_frontend() -> None:
    hp = ROOT / 'app' / 'static' / 'index.html'
    h = hp.read_text()
    h = h.replace('V2.2 · Ratings + Personalization', 'V2.4 · Faster filters + Rentals')
    h = h.replace('V2.2.3', 'V2.4.0')
    h = h.replace('<button class="secondary" onclick="setQuickFilter(\'tv\')">📺 New Shows</button>', '<button class="secondary" onclick="setQuickFilter(\'tv\')">📺 New Shows</button>\n          <button class="secondary" onclick="surpriseMe()">🎲 Surprise Me</button>')
    controls = '<section class="controls" id="controls">'
    if 'id="browseMode"' not in h:
        h = h.replace(controls, '''<div class="browse-mode segmented" id="browseMode" aria-label="Availability mode">\n      <button class="active" data-browse="subscription" onclick="setBrowseMode('subscription')">▶ Included with my services</button>\n      <button data-browse="rent" onclick="setBrowseMode('rent')">💳 Available to Rent</button>\n    </div>\n    ''' + controls)
    if 'id="presetSelect"' not in h:
        h = h.replace('<button id="clearFilters" class="filter-clear" type="button">↺ Clear filters</button>', '''<select id="presetSelect" aria-label="Saved filter preset" onchange="applyPreset(this.value)"><option value="">Saved presets…</option></select>\n      <button class="filter-clear" type="button" onclick="savePreset()">☆ Save preset</button>\n      <button class="filter-clear" type="button" onclick="deletePreset()">⌫ Delete preset</button>\n      <button id="clearFilters" class="filter-clear" type="button">↺ Clear filters</button>''')
    if 'id="activeFilterSummary"' not in h:
        h = h.replace('</section>\n\n    <section class="section-head">', '</section>\n    <div id="activeFilterSummary" class="active-filter-summary">Included · Movies · Last 60 days</div>\n\n    <section class="section-head">', 1)
    hp.write_text(h)

    jp = ROOT / 'app' / 'static' / 'app.js'
    js = jp.read_text()
    if 'streamScoutBrowseMode' not in js:
        js = 'window.streamScoutBrowseMode = window.streamScoutBrowseMode || "subscription";\n' + js

    helper = r'''
function rentalNames(x){return (x.rental_providers||[]).map(p=>p.name).filter(Boolean)}
function hydrateRentalBadges(items){
 for(const x of items||[]){const names=rentalNames(x);if(!names.length)continue;const anchor=document.querySelector(`[data-match-key="${x.media_type}:${x.id}"]`);const cardEl=anchor?.closest('.card');if(cardEl&&!cardEl.querySelector('.rent-line')){const div=document.createElement('div');div.className='rent-line';div.textContent='Rent: '+names.slice(0,4).join(' · ');cardEl.appendChild(div)}}
}
function selectedText(id){const el=$(id);return el&&el.selectedIndex>=0?el.options[el.selectedIndex].text:''}
function updateFilterSummary(){const parts=[window.streamScoutBrowseMode==='rent'?'Available to Rent':'Included',state.mediaType==='movie'?'Movies':'TV'];const ids=['#smartGenre','#contentRating','#days','#runtime','#decade'];for(const id of ids){const el=$(id);if(el&&el.value){let t=selectedText(id);if(t&&!/^All |^Any /.test(t))parts.push(t)}}const el=$('#activeFilterSummary');if(el)el.textContent=parts.join(' · ')}
function setBrowseMode(mode){window.streamScoutBrowseMode=mode==='rent'?'rent':'subscription';$$('[data-browse]').forEach(b=>b.classList.toggle('active',b.dataset.browse===window.streamScoutBrowseMode));const tv=document.querySelector('[data-type="tv"]');if(tv){tv.disabled=window.streamScoutBrowseMode==='rent';tv.title=window.streamScoutBrowseMode==='rent'?'Rental search is movie-first':''}if(window.streamScoutBrowseMode==='rent'&&state.mediaType!=='movie'){state.mediaType='movie';$$('[data-type]').forEach(b=>b.classList.toggle('active',b.dataset.type==='movie'));$('#limitedWrap')?.classList.add('hidden')}state.page=1;updateFilterSummary();loadDiscover()}
function captureFilters(){return {mediaType:state.mediaType,browse:window.streamScoutBrowseMode,days:$('#days').value,genre:$('#genre').value,smartGenre:$('#smartGenre').value,rating:$('#rating').value,contentRating:$('#contentRating').value,runtime:$('#runtime').value,decade:$('#decade').value,sort:$('#sort').value,limited:!!$('#limitedSeries')?.checked}}
function presetStore(){try{return JSON.parse(localStorage.getItem('streamScoutPresets')||'{}')}catch(e){return {}}}
function loadPresetOptions(){const el=$('#presetSelect');if(!el)return;const store=presetStore(),cur=el.value;el.innerHTML='<option value="">Saved presets…</option>'+Object.keys(store).sort().map(n=>`<option value="${esc(n)}">${esc(n)}</option>`).join('');if(store[cur])el.value=cur}
function savePreset(){const name=(prompt('Name this filter preset:')||'').trim();if(!name)return;const store=presetStore();store[name]=captureFilters();localStorage.setItem('streamScoutPresets',JSON.stringify(store));loadPresetOptions();$('#presetSelect').value=name;toast('Preset saved')}
function applyPreset(name){if(!name)return;const p=presetStore()[name];if(!p)return;window.streamScoutBrowseMode=p.browse||'subscription';state.mediaType=p.mediaType||'movie';$$('[data-browse]').forEach(b=>b.classList.toggle('active',b.dataset.browse===window.streamScoutBrowseMode));$$('[data-type]').forEach(b=>b.classList.toggle('active',b.dataset.type===state.mediaType));for(const [id,key] of [['#days','days'],['#genre','genre'],['#rating','rating'],['#contentRating','contentRating'],['#runtime','runtime'],['#decade','decade'],['#sort','sort']]){if($(id))$(id).value=p[key]??''}renderSmartGenres();if($('#smartGenre'))$('#smartGenre').value=p.smartGenre||'';if($('#limitedSeries'))$('#limitedSeries').checked=!!p.limited;state.page=1;updateFilterSummary();loadDiscover()}
function deletePreset(){const el=$('#presetSelect'),name=el?.value;if(!name)return;const store=presetStore();delete store[name];localStorage.setItem('streamScoutPresets',JSON.stringify(store));loadPresetOptions();toast('Preset deleted')}
function surpriseMe(){const rows=(state.lastResults||[]).filter(x=>!x.hidden);if(!rows.length){toast('Load some results first');return}const x=rows[Math.floor(Math.random()*rows.length)];openDetail(x.media_type,x.id)}
'''

    new_discover = r'''async function loadDiscover(){state.mode='discover';$('#controls').classList.remove('hidden');const rental=window.streamScoutBrowseMode==='rent';$('#sectionEyebrow').textContent=rental?'RENTAL CATALOG':'RECENT RELEASES';$('#sectionTitle').textContent=rental?'Movies available to rent':`${state.mediaType==='movie'?'Movies':'TV shows'} on your services`;const q=new URLSearchParams({media_type:state.mediaType,days:$('#days').value,min_rating:$('#rating').value,page:state.page,sort:$('#sort').value,monetization_type:window.streamScoutBrowseMode});if($('#genre').value)q.set('genre_id',$('#genre').value);if($('#smartGenre').value)q.set('smart_genre',$('#smartGenre').value);if($('#contentRating').value)q.set('content_rating',$('#contentRating').value);if($('#runtime').value)q.set('runtime',$('#runtime').value);if($('#decade').value)q.set('decade',$('#decade').value);if(state.mediaType==='tv'&&$('#limitedSeries').checked)q.set('limited_series','true');updateFilterSummary();try{const d=await api('/api/discover?'+q);state.totalPages=d.total_pages;render(d.results);renderPager()}catch(e){render([]);$('#empty').innerHTML=`<h3>Couldn’t load titles</h3><p>${esc(e.message)}</p>`}}
'''
    js = re.sub(r'async function loadDiscover\(\)\{.*?\}\nasync function loadProviders', helper + '\n' + new_discover + 'async function loadProviders', js, count=1, flags=re.S)

    new_render = r'''function render(items){state.lastResults=items;$('#grid').innerHTML=items.map(card).join('');$('#empty').classList.toggle('hidden',items.length>0);if(!items.length)$('#empty').innerHTML='<h3>No exact matches.</h3><p>Stream Scout did not relax your filters. Change one filter if you want broader results.</p>';hydrateRentalBadges(items);setTimeout(()=>hydrateRatings(items.slice(0,20)),0);setTimeout(()=>hydrateMatch(items),0);updateFilterSummary();}
'''
    js = re.sub(r'function render\(items\)\{.*?\}\nasync function hydrateRatings', new_render + 'async function hydrateRatings', js, count=1, flags=re.S)
    if 'loadPresetOptions();' not in js[-1200:]:
        js += "\nwindow.addEventListener('DOMContentLoaded',()=>{loadPresetOptions();updateFilterSummary();});\n"
    jp.write_text(js)

    cp = ROOT / 'app' / 'static' / 'styles.css'
    css = cp.read_text()
    if '.active-filter-summary' not in css:
        css += r'''

/* Stream Scout v2.4 usability */
.browse-mode{display:flex;gap:6px;margin:12px 0 10px;position:sticky;top:64px;z-index:16;background:var(--bg,#0c0d11);padding:8px 0}
.browse-mode button{flex:1;max-width:300px}
.active-filter-summary{position:sticky;top:118px;z-index:15;margin:0 0 12px;padding:9px 12px;border-radius:12px;background:rgba(18,20,28,.94);backdrop-filter:blur(12px);font-size:.84rem;opacity:.9;border:1px solid rgba(255,255,255,.08)}
.rent-line{margin:8px 10px 10px;font-size:.78rem;line-height:1.3;padding:7px 9px;border-radius:9px;background:rgba(255,255,255,.07);opacity:.95}
[data-type="tv"]:disabled{opacity:.4;cursor:not-allowed}
@media(max-width:700px){.browse-mode{top:55px}.active-filter-summary{top:108px;font-size:.76rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
'''
    cp.write_text(css)


if __name__ == '__main__':
    patch_main()
    patch_frontend()
