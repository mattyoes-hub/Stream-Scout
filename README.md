# Stream Scout Cloud

Private household streaming discovery app for Matt + Jake.

## Cloud deployment

- FastAPI serves the API and static frontend.
- Railway hosts the service.
- Supabase PostgreSQL stores Stream Scout data in the `stream_scout` schema.
- TMDB supplies catalog/streaming metadata.
- OMDb supplies IMDb and Rotten Tomatoes ratings.

### Required Railway environment variables

- `DATABASE_URL`
- `DB_SCHEMA=stream_scout`
- `TMDB_BEARER_TOKEN`
- `OMDB_API_KEY`
- `REGION=US`

Start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```
