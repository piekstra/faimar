"""faimar — fair market value explorer.

Run locally:
    .venv/bin/uvicorn app.main:app --reload

API:
    GET /api/v1/valuation/{symbol}
"""

import re
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .cache import Cache
from .history import FairValueLog
from .providers import nasdaq, yahoo
from .valuation import build_valuation, merge_fair_value_history

app = FastAPI(title="faimar", version="0.1.0")
cache = Cache(config.CACHE_PATH)
fair_value_log = FairValueLog(config.CACHE_PATH)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
SYMBOL_RE = re.compile(r"^[A-Za-z0-9.^=-]{1,12}$")


@app.get("/api/v1/valuation/{symbol}")
def valuation(symbol: str) -> dict:
    if not SYMBOL_RE.match(symbol):
        raise HTTPException(status_code=400, detail="Invalid symbol")
    sym = symbol.upper()

    try:
        fundamentals, fundamentals_age = cache.fetch(
            f"fundamentals:{sym}",
            config.TTL_FUNDAMENTALS,
            lambda: yahoo.fetch_fundamentals(sym),
        )
        prices, prices_age = cache.fetch(
            f"prices:{sym}", config.TTL_PRICES, lambda: yahoo.fetch_prices(sym)
        )
    except yahoo.SymbolNotFound:
        raise HTTPException(status_code=404, detail=f"Unknown symbol: {sym}")

    risk_free, _ = cache.fetch(
        "risk_free", config.TTL_RISK_FREE, yahoo.fetch_risk_free
    )

    # Best-effort: consensus target history is enrichment, never a blocker.
    try:
        targets, _ = cache.fetch(
            f"targets:{sym}",
            config.TTL_FUNDAMENTALS,
            lambda: nasdaq.fetch_target_history(sym),
        )
    except Exception:
        targets = {"history": []}

    payload = build_valuation(
        fundamentals, prices, risk_free.get("risk_free"), targets.get("history")
    )

    # Record today's estimate and fold past recorded revisions into the
    # chart history — the step line grows richer the longer faimar runs.
    if payload["fair_value"] is not None:
        fair_value_log.record(sym, str(date.today()), payload["fair_value"], payload["method"])
    payload["history"]["fair_values"] = merge_fair_value_history(
        payload["history"]["fair_values"], fair_value_log.series(sym)
    )

    payload["cache"] = {
        "fundamentals_age_s": round(fundamentals_age),
        "prices_age_s": round(prices_age),
    }
    return payload


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/", StaticFiles(directory=STATIC_DIR), name="static")
