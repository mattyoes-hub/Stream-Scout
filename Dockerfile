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

# PostgreSQL returns timestamptz values as datetime objects rather than strings.
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

# Build-time trace for discover/filter plumbing; safe to remove after diagnosis.
lines = s.splitlines()
for i, line in enumerate(lines):
    if 'def discover' in line or 'smart_genre' in line or 'content_rating' in line or 'tmdb.discover' in line:
        lo=max(0,i-5); hi=min(len(lines),i+10)
        print(f'--- main.py lines {lo+1}-{hi} ---')
        for n in range(lo,hi):
            print(f'{n+1}: {lines[n]}')

# Menu Planner's Railway DATABASE_URL uses SQLAlchemy's postgresql+psycopg scheme.
# psycopg.connect expects a plain PostgreSQL scheme.
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
