from pathlib import Path
import re

ROOT = Path('/app')

jp = ROOT / 'app' / 'static' / 'app.js'
js = jp.read_text()

# Background enrichment must never compete with browsing/navigation. Normalize
# whatever earlier patches produced into a much lighter schedule.
js = re.sub(
    r'setTimeout\(\(\)=>hydrateRatings\(items\.slice\(0,\d+\)\),\d+\)',
    'setTimeout(()=>hydrateRatings(items.slice(0,4)),12000)',
    js,
)
js = re.sub(
    r'setTimeout\(\(\)=>hydrateMatch\(items(?:\.slice\(0,\d+\))?\),\d+\)',
    'setTimeout(()=>hydrateMatch(items.slice(0,4)),18000)',
    js,
)

jp.write_text(js)
