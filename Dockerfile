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
# then apply the cloud/runtime/UI patch in one normal Python source file.
RUN cp /src/app/tmdb.py /app/app/tmdb.py && \
    cp /src/app/omdb.py /app/app/omdb.py && \
    python /src/app/cloud_patch.py && \
    python - <<'PY'
from pathlib import Path
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
