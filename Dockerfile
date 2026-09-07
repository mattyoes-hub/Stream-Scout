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
# Keep the local/SQLite-era season-alert logic compatible with both.
p = Path('/app/app/main.py')
s = p.read_text()
s = s.replace(
    'watched_date=(row.get("updated_at") or "")[:10]',
    'watched_raw=row.get("updated_at"); watched_date=(watched_raw.date().isoformat() if hasattr(watched_raw, "date") else str(watched_raw or "")[:10])'
)
p.write_text(s)
PY

RUN pip install --no-cache-dir -r requirements.txt

ENV PYTHONUNBUFFERED=1
EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
