from __future__ import annotations

import os
from contextlib import AbstractContextManager
from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DB_SCHEMA = os.getenv("DB_SCHEMA", "stream_scout").strip() or "stream_scout"


class CursorAdapter:
    def __init__(self, cursor):
        self._cursor = cursor

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()


class ConnectionAdapter(AbstractContextManager):
    def __init__(self):
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL is not configured")
        self._conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        self._conn.execute(f'SET search_path TO "{DB_SCHEMA}", public')

    @staticmethod
    def _translate(sql: str) -> str:
        return sql.replace("?", "%s")

    def execute(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> CursorAdapter:
        cur = self._conn.execute(self._translate(sql), params)
        return CursorAdapter(cur)

    def executemany(self, sql: str, params_seq: Iterable[tuple[Any, ...]]) -> None:
        with self._conn.cursor() as cur:
            cur.executemany(self._translate(sql), params_seq)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._conn.commit()
        else:
            self._conn.rollback()
        self._conn.close()
        return False


def connect() -> ConnectionAdapter:
    return ConnectionAdapter()


def init_db() -> None:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")

    ddl = f'''\
    CREATE SCHEMA IF NOT EXISTS "{DB_SCHEMA}";
    SET search_path TO "{DB_SCHEMA}", public;

    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS providers (
        provider_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        logo_path TEXT,
        selected INTEGER NOT NULL DEFAULT 0,
        display_priority INTEGER NOT NULL DEFAULT 999
    );
    CREATE TABLE IF NOT EXISTS rt_cache (
        media_type TEXT NOT NULL,
        tmdb_id INTEGER NOT NULL,
        imdb_id TEXT,
        score TEXT,
        fetched_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (media_type, tmdb_id)
    );
    CREATE TABLE IF NOT EXISTS ratings_cache (
        media_type TEXT NOT NULL,
        tmdb_id INTEGER NOT NULL,
        imdb_id TEXT,
        imdb_score TEXT,
        rt_score TEXT,
        metacritic_score TEXT,
        source_title TEXT,
        fetched_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (media_type, tmdb_id)
    );
    CREATE TABLE IF NOT EXISTS library (
        media_type TEXT NOT NULL,
        tmdb_id INTEGER NOT NULL,
        status TEXT,
        rating TEXT,
        hidden INTEGER NOT NULL DEFAULT 0,
        queue_bucket TEXT,
        added_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (media_type, tmdb_id)
    );
    CREATE TABLE IF NOT EXISTS profiles (
        id BIGSERIAL PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        emoji TEXT NOT NULL DEFAULT '🙂',
        display_order INTEGER NOT NULL DEFAULT 99,
        created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS profile_title_state (
        profile_id BIGINT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
        media_type TEXT NOT NULL,
        tmdb_id INTEGER NOT NULL,
        rating TEXT,
        favorite INTEGER NOT NULL DEFAULT 0,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (profile_id, media_type, tmdb_id)
    );
    CREATE TABLE IF NOT EXISTS watch_history (
        id BIGSERIAL PRIMARY KEY,
        media_type TEXT NOT NULL,
        tmdb_id INTEGER NOT NULL,
        watched_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS catalog_seen (
        media_type TEXT NOT NULL,
        tmdb_id INTEGER NOT NULL,
        first_seen TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_seen TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (media_type, tmdb_id)
    );
    CREATE TABLE IF NOT EXISTS catalog_provider_seen (
        media_type TEXT NOT NULL,
        tmdb_id INTEGER NOT NULL,
        provider_id INTEGER NOT NULL,
        first_seen TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_seen TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (media_type, tmdb_id, provider_id)
    );
    CREATE TABLE IF NOT EXISTS season_seen (
        tmdb_id INTEGER PRIMARY KEY,
        season_count INTEGER NOT NULL DEFAULT 0,
        latest_season_number INTEGER,
        latest_air_date TEXT,
        checked_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    '''
    raw = psycopg.connect(DATABASE_URL)
    try:
        raw.execute(ddl)
        raw.commit()
    finally:
        raw.close()

    with connect() as conn:
        conn.execute("INSERT INTO profiles(name,emoji,display_order) VALUES('Matt','😎',1) ON CONFLICT(name) DO NOTHING")
        conn.execute("INSERT INTO profiles(name,emoji,display_order) VALUES('Jake','🎬',2) ON CONFLICT(name) DO NOTHING")
        conn.execute("""INSERT INTO ratings_cache(media_type,tmdb_id,imdb_id,rt_score,fetched_at)
                        SELECT media_type,tmdb_id,imdb_id,score,fetched_at FROM rt_cache WHERE score IS NOT NULL
                        ON CONFLICT(media_type,tmdb_id) DO NOTHING""")


def rows(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with connect() as conn:
        return list(conn.execute(sql, params).fetchall())


def row(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    with connect() as conn:
        return conn.execute(sql, params).fetchone()


def execute(sql: str, params: tuple[Any, ...] = ()) -> None:
    with connect() as conn:
        conn.execute(sql, params)
