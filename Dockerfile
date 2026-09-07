FROM python:3.13-slim

WORKDIR /app
COPY payload /tmp/payload
COPY app /src/app

RUN cat /tmp/payload/part* | base64 -d > /tmp/stream-scout-cloud.zip && \
    python - <<'PY'
from pathlib import Path
import zipfile
z = Path('/tmp/stream-scout-cloud.zip')
with zipfile.ZipFile(z) as f:
    f.extractall('/app')
PY

# Prefer maintainable source files from the repository for API integrations,
# then apply the cloud/runtime/UI patches in normal Python source files.
RUN cp /src/app/tmdb.py /app/app/tmdb.py && \
    cp /src/app/omdb.py /app/app/omdb.py && \
    python /src/app/cloud_patch.py && \
    python /src/app/hotfix_v24.py && \
    python /src/app/hotfix_v25.py && \
    python /src/app/hotfix_v26.py && \
    python - <<'PY'
from pathlib import Path
p = Path('/app/app/db.py')
s = p.read_text()
s = s.replace(
    'DATABASE_URL = os.getenv("DATABASE_URL", "").strip()\n',
    'DATABASE_URL = os.getenv("DATABASE_URL", "").strip()\nif DATABASE_URL.startswith("postgresql+psycopg://"):\n    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgresql+psycopg://"):]\n'
)
p.write_text(s)

# Internal QA endpoint retained for targeted verification.
p = Path('/app/app/main.py')
s = p.read_text()
if '/api/smoke_v24' not in s:
    anchor = '@app.get("/api/search")'
    smoke = '''@app.get("/api/smoke_v24")\nasync def smoke_v24():\n    import time\n    t0 = time.perf_counter()\n    strict = await discover(\n        media_type="movie", days=0, genre_id=35, min_rating=0, page=1, sort="popular",\n        content_rating="R", smart_genre="dark_comedy", runtime=None, decade=None,\n        limited_series=False, monetization_type="subscription",\n    )\n    strict_rows = strict.get("results", [])\n    strict_ratings = await asyncio.gather(*(tmdb.content_rating_for("movie", int(x["id"])) for x in strict_rows[:10])) if strict_rows else []\n    if any(r != "R" for r in strict_ratings):\n        raise HTTPException(500, f"Strict R validation failed: {strict_ratings}")\n    t1 = time.perf_counter()\n    rent = await discover(\n        media_type="movie", days=0, genre_id=None, min_rating=0, page=1, sort="popular",\n        content_rating=None, smart_genre=None, runtime=None, decade=None,\n        limited_series=False, monetization_type="rent",\n    )\n    rent_rows = rent.get("results", [])\n    t2 = time.perf_counter()\n    result = {\n        "ok": True, "version": BUILD_VERSION,\n        "dark_comedy_r_count": len(strict_rows), "verified_r": len(strict_ratings),\n        "rental_count": len(rent_rows),\n        "dark_comedy_r_seconds": round(t1-t0, 3), "rental_seconds": round(t2-t1, 3),\n    }\n    print("V24_SMOKE", json.dumps(result), flush=True)\n    return result\n\n\n'''
    s = s.replace(anchor, smoke + anchor, 1)
    p.write_text(s)
PY

# Production browser bundle must at least parse before Railway is allowed to deploy it.
RUN apt-get update && \
    apt-get install -y --no-install-recommends nodejs && \
    node --check /app/app/static/app.js && \
    apt-get purge -y nodejs && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir -r requirements.txt

ENV PYTHONUNBUFFERED=1
EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
