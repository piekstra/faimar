"""Yahoo Finance data provider (via yfinance — free, no API key).

Everything returned here is a plain JSON-serializable dict so it can go
straight into the cache. yfinance field names shift between releases, so
each extraction is defensive: missing data degrades to None rather than
raising, and the valuation layer decides what it can do with what's left.
"""

import math
from typing import Any

import yfinance as yf


class SymbolNotFound(Exception):
    pass


def _clean(value: Any) -> float | None:
    """NaN/inf/None-safe float extraction."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _row_series(df, row_name: str) -> dict[str, float]:
    """Extract one row of a yfinance statement DataFrame as {iso_date: value}."""
    out: dict[str, float] = {}
    if df is None or getattr(df, "empty", True) or row_name not in df.index:
        return out
    for col, value in df.loc[row_name].items():
        v = _clean(value)
        if v is not None:
            out[str(col.date() if hasattr(col, "date") else col)] = v
    return out


def _free_cash_flow_rows(df) -> dict[str, float]:
    """FCF per period; falls back to OCF - CapEx when no FCF row exists."""
    fcf = _row_series(df, "Free Cash Flow")
    if fcf:
        return fcf
    ocf = _row_series(df, "Operating Cash Flow")
    capex = _row_series(df, "Capital Expenditure")  # reported negative
    return {d: ocf[d] + capex.get(d, 0.0) for d in ocf}


def fetch_fundamentals(symbol: str) -> dict:
    t = yf.Ticker(symbol)
    info = t.info or {}
    if not info.get("regularMarketPrice") and not info.get("shortName"):
        raise SymbolNotFound(f"No data for symbol {symbol!r}")

    annual_fcf = _free_cash_flow_rows(_safe(lambda: t.cash_flow))
    quarterly_fcf = _free_cash_flow_rows(_safe(lambda: t.quarterly_cash_flow))

    # TTM FCF: sum of the four most recent quarters, else Yahoo's own TTM
    # figure, else the most recent annual figure.
    fcf_ttm = None
    if len(quarterly_fcf) >= 4:
        recent = sorted(quarterly_fcf)[-4:]
        fcf_ttm = sum(quarterly_fcf[d] for d in recent)
    if fcf_ttm is None:
        fcf_ttm = _clean(info.get("freeCashflow"))
    if fcf_ttm is None and annual_fcf:
        fcf_ttm = annual_fcf[max(annual_fcf)]

    # Historical diluted share counts let us compute per-share fair value
    # for past years without survivorship from buybacks/dilution.
    shares_by_year = _row_series(_safe(lambda: t.income_stmt), "Diluted Average Shares")

    return {
        "symbol": symbol.upper(),
        "name": info.get("longName") or info.get("shortName") or symbol.upper(),
        "currency": info.get("currency") or "USD",
        "beta": _clean(info.get("beta")),
        "shares_outstanding": _clean(info.get("sharesOutstanding")),
        "fcf_ttm": fcf_ttm,
        "annual_fcf": annual_fcf,
        "shares_by_year": shares_by_year,
        "growth_estimate": _growth_estimate(t, info, annual_fcf),
        "analyst": {
            "target_mean": _clean(info.get("targetMeanPrice")),
            "target_high": _clean(info.get("targetHighPrice")),
            "target_low": _clean(info.get("targetLowPrice")),
            "count": _clean(info.get("numberOfAnalystOpinions")),
        },
    }


def fetch_prices(symbol: str) -> dict:
    t = yf.Ticker(symbol)
    hist = t.history(period="5y", interval="1d", auto_adjust=True)
    if hist is None or hist.empty:
        raise SymbolNotFound(f"No price history for symbol {symbol!r}")
    closes = [
        [str(idx.date()), round(float(close), 4)]
        for idx, close in hist["Close"].items()
        if _clean(close) is not None
    ]
    return {"prices": closes, "current_price": closes[-1][1]}


def fetch_risk_free() -> dict:
    """10-year US Treasury yield via ^TNX (quoted in percent)."""
    hist = yf.Ticker("^TNX").history(period="5d")
    rate = None
    if hist is not None and not hist.empty:
        rate = _clean(hist["Close"].iloc[-1])
    return {"risk_free": rate / 100.0 if rate else None}


def _growth_estimate(t, info: dict, annual_fcf: dict[str, float]) -> dict:
    """Best available forward growth rate, with its provenance."""
    try:
        ge = t.growth_estimates
        for period in ("+1y", "0y"):
            if ge is not None and period in ge.index:
                row = ge.loc[period]
                # Column has been renamed across yfinance releases.
                for col in ("stockTrend", "stock"):
                    if col in row:
                        v = _clean(row[col])
                        if v is not None:
                            return {"rate": v, "source": f"analyst {period} estimate"}
    except Exception:
        pass
    for field, source in (
        ("earningsGrowth", "trailing earnings growth"),
        ("revenueGrowth", "trailing revenue growth"),
    ):
        v = _clean(info.get(field))
        if v is not None:
            return {"rate": v, "source": source}
    cagr = _fcf_cagr(annual_fcf)
    if cagr is not None:
        return {"rate": cagr, "source": "historical FCF CAGR"}
    return {"rate": None, "source": "none"}


def _fcf_cagr(annual_fcf: dict[str, float]) -> float | None:
    if len(annual_fcf) < 2:
        return None
    dates = sorted(annual_fcf)
    first, last = annual_fcf[dates[0]], annual_fcf[dates[-1]]
    years = len(dates) - 1
    if first <= 0 or last <= 0:
        return None
    return (last / first) ** (1 / years) - 1


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None
