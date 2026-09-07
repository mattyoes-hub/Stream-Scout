FROM python:3.13-slim

WORKDIR /app
COPY payload /tmp/payload

RUN cat /tmp/payload/part* | base64 -d > /tmp/stream-scout-cloud.zip && \
    python - <<'PY'
from pathlib import Path
import zipfile
z = Path('/tmp/stream-scout-cloud.zip')
with zipfile.ZipFile(z) as f:
    f.extractall('/app')

p = Path('/app/app/main.py')
s = p.read_text()
s = s.replace(
    'watched_date=(row.get("updated_at") or "")[:10]',
    'watched_raw=row.get("updated_at"); watched_date=(watched_raw.date().isoformat() if hasattr(watched_raw, "date") else str(watched_raw or "")[:10])'
)
s = s.replace(
    '@app.get("/api/health")\ndef health():',
    '@app.get("/health")\ndef railway_health():\n    return {"ok": True}\n\n\n@app.get("/api/health")\ndef health():'
)
p.write_text(s)

# Temporary build-time inspection of frontend patch points.
for fp in [Path('/app/app/static/app.js'), Path('/app/app/static/index.html')]:
    if not fp.exists():
        continue
    txt = fp.read_text(errors='ignore')
    print(f'=== FRONTEND FILE {fp} chars={len(txt)} ===')
    needles = ['ratings-batch','match-batch','/api/discover','content_rating','smart_genre','Clear Filters','Tonight','Surprise','Rent','filter','renderCards','loadRatings']
    for needle in needles:
        start = 0
        hits = 0
        while True:
            i = txt.find(needle, start)
            if i < 0 or hits >= 4:
                break
            lo=max(0,i-700); hi=min(len(txt),i+1300)
            print(f'--- {fp.name} needle={needle} at={i} ---')
            print(txt[lo:hi])
            start=i+len(needle); hits += 1

p = Path('/app/app/db.py')
s = p.read_text()
s = s.replace(
    'DATABASE_URL = os.getenv("DATABASE_URL", "").strip()\n',
    'DATABASE_URL = os.getenv("DATABASE_URL", "").strip()\nif DATABASE_URL.startswith("postgresql+psycopg://"):\n    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgresql+psycopg://"):]\n'
)
p.write_text(s)
PY

RUN pip install --no-cache-dir -r requirements.txt

ENV PYTHONUNBUFFERED=1
EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
