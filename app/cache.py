"""SQLite-backed TTL cache with stale-while-error semantics.

A single file keeps local runs zero-setup and survives restarts. The
interface is intentionally tiny (get/set/fetch) so a hosted deployment
can swap in Redis or Postgres behind the same three methods.
"""

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable


class Cache:
    def __init__(self, path: Path | str):
        self._path = str(path)
        self._lock = threading.Lock()
        with self._conn() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS cache ("
                "  key TEXT PRIMARY KEY,"
                "  payload TEXT NOT NULL,"
                "  fetched_at REAL NOT NULL"
                ")"
            )

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def get(self, key: str, ttl: float) -> tuple[Any, float] | None:
        """Return (value, age_seconds) if a fresh entry exists, else None."""
        row = self._read(key)
        if row is None:
            return None
        payload, fetched_at = row
        age = time.time() - fetched_at
        if age > ttl:
            return None
        return json.loads(payload), age

    def get_stale(self, key: str) -> tuple[Any, float] | None:
        """Return (value, age_seconds) regardless of TTL, else None."""
        row = self._read(key)
        if row is None:
            return None
        payload, fetched_at = row
        return json.loads(payload), time.time() - fetched_at

    def set(self, key: str, value: Any) -> None:
        payload = json.dumps(value)
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO cache (key, payload, fetched_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET payload=excluded.payload, "
                "fetched_at=excluded.fetched_at",
                (key, payload, time.time()),
            )

    def fetch(self, key: str, ttl: float, fetch_fn: Callable[[], Any]) -> tuple[Any, float]:
        """Return cached value if fresh; otherwise call fetch_fn.

        If fetch_fn raises but a stale entry exists, serve the stale entry
        rather than failing — upstream (Yahoo) hiccups shouldn't take the
        site down.
        """
        hit = self.get(key, ttl)
        if hit is not None:
            return hit
        try:
            value = fetch_fn()
        except Exception:
            stale = self.get_stale(key)
            if stale is not None:
                return stale
            raise
        self.set(key, value)
        return value, 0.0

    def _read(self, key: str) -> tuple[str, float] | None:
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT payload, fetched_at FROM cache WHERE key = ?", (key,)
            )
            return cur.fetchone()
