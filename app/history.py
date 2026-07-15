"""Persistent log of faimar's own fair value estimates.

Charts like Simply Wall St's show fair value stepping at each revision —
history their proprietary models have been accumulating for years. No
free source sells that backlog, so faimar builds its own: every computed
estimate is recorded once per day, and the chart replays the revisions.
The longer the app runs, the richer the step history gets.
"""

import sqlite3
import threading
from pathlib import Path


class FairValueLog:
    def __init__(self, path: Path | str):
        self._path = str(path)
        self._lock = threading.Lock()
        with self._conn() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS fair_value_log ("
                "  symbol TEXT NOT NULL,"
                "  date TEXT NOT NULL,"
                "  fair_value REAL NOT NULL,"
                "  method TEXT NOT NULL,"
                "  PRIMARY KEY (symbol, date)"
                ")"
            )

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def record(self, symbol: str, day: str, fair_value: float, method: str) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO fair_value_log (symbol, date, fair_value, method) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(symbol, date) DO UPDATE SET "
                "fair_value=excluded.fair_value, method=excluded.method",
                (symbol, day, fair_value, method),
            )

    def series(self, symbol: str, tolerance: float = 0.01) -> list[list]:
        """Logged estimates as [[date, value], ...], collapsed to revision
        points: consecutive days within `tolerance` (relative) of the last
        kept value are dropped, so the series only steps when the estimate
        meaningfully changed."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT date, fair_value FROM fair_value_log "
                "WHERE symbol = ? ORDER BY date",
                (symbol,),
            ).fetchall()
        points: list[list] = []
        for day, value in rows:
            if points:
                prev = points[-1][1]
                threshold = tolerance * abs(prev) if prev else 0.0
                if abs(value - prev) <= threshold:
                    continue
            points.append([day, value])
        return points
