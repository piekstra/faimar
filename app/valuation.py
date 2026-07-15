"""Fair value estimation.

Primary model: two-stage discounted cash flow on levered free cash flow,
the same family of model Simply Wall St / Morningstar style "fair value"
charts are built on:

  1. Start from trailing-twelve-month free cash flow.
  2. Grow it at an analyst-informed rate that fades linearly to a
     terminal rate over FORECAST_YEARS.
  3. Add a Gordon-growth terminal value.
  4. Discount everything at CAPM (risk-free + beta * equity risk premium).
  5. Divide by shares outstanding.

All growth/beta/discount inputs are clamped (see config) so one weird
data point can't produce a comical fair value. When FCF is negative or
missing the model can't run, so we fall back to the mean analyst price
target and label the result accordingly.
"""

from dataclasses import dataclass
from datetime import date

from . import config


@dataclass
class DcfInputs:
    base_fcf: float
    growth: float
    terminal_growth: float
    discount_rate: float
    shares_outstanding: float


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def discount_rate(beta: float | None, risk_free: float) -> float:
    b = clamp(beta if beta is not None else 1.0, config.BETA_FLOOR, config.BETA_CAP)
    return clamp(
        risk_free + b * config.EQUITY_RISK_PREMIUM,
        config.DISCOUNT_FLOOR,
        config.DISCOUNT_CAP,
    )


def dcf_fair_value(inp: DcfInputs) -> float | None:
    """Per-share equity value from a fading-growth DCF."""
    if inp.base_fcf <= 0 or inp.shares_outstanding <= 0:
        return None
    if inp.discount_rate <= inp.terminal_growth:
        return None

    years = config.FORECAST_YEARS
    fcf = inp.base_fcf
    total_pv = 0.0
    for year in range(1, years + 1):
        # Linear fade from the stage-1 rate to the terminal rate.
        fade = (year - 1) / max(years - 1, 1)
        g = inp.growth + (inp.terminal_growth - inp.growth) * fade
        fcf *= 1 + g
        total_pv += fcf / (1 + inp.discount_rate) ** year

    terminal = fcf * (1 + inp.terminal_growth) / (inp.discount_rate - inp.terminal_growth)
    total_pv += terminal / (1 + inp.discount_rate) ** years
    return total_pv / inp.shares_outstanding


def verdict(upside_pct: float | None) -> str:
    """Same 20% bands Simply Wall St uses for its price-vs-value calls."""
    if upside_pct is None:
        return "unknown"
    if upside_pct >= 20:
        return "undervalued"
    if upside_pct <= -20:
        return "overvalued"
    return "fair"


def build_valuation(fundamentals: dict, prices: dict, risk_free: float | None) -> dict:
    rf = risk_free if risk_free is not None else config.DEFAULT_RISK_FREE
    terminal_growth = min(rf, config.TERMINAL_GROWTH_CAP)

    raw_growth = fundamentals.get("growth_estimate", {}).get("rate")
    growth = clamp(
        raw_growth if raw_growth is not None else 0.05,
        config.GROWTH_FLOOR,
        config.GROWTH_CAP,
    )
    rate = discount_rate(fundamentals.get("beta"), rf)
    shares = fundamentals.get("shares_outstanding")
    fcf_ttm = fundamentals.get("fcf_ttm")

    current_price = prices["current_price"]

    dcf_value = None
    if fcf_ttm is not None and shares:
        dcf_value = dcf_fair_value(
            DcfInputs(fcf_ttm, growth, terminal_growth, rate, shares)
        )

    # A trailing-FCF DCF is only informative when the company actually
    # produces meaningful FCF relative to its market cap; below the yield
    # floor (growth companies), analyst consensus is the better free signal.
    market_cap = current_price * shares if shares else None
    fcf_yield = fcf_ttm / market_cap if fcf_ttm and market_cap else None
    target = fundamentals.get("analyst", {}).get("target_mean")

    fair_value = None
    method = "unavailable"
    if dcf_value is not None and fcf_yield is not None and fcf_yield >= config.MIN_FCF_YIELD:
        fair_value, method = dcf_value, "dcf"
    elif target:
        fair_value, method = target, "analyst_target"
    elif dcf_value is not None:
        fair_value, method = dcf_value, "dcf"

    upside_pct = None
    if fair_value:
        upside_pct = (fair_value - current_price) / current_price * 100

    return {
        "symbol": fundamentals["symbol"],
        "name": fundamentals["name"],
        "currency": fundamentals["currency"],
        "price": current_price,
        "fair_value": round(fair_value, 2) if fair_value is not None else None,
        "upside_pct": round(upside_pct, 1) if upside_pct is not None else None,
        "verdict": verdict(upside_pct),
        "method": method,
        "assumptions": {
            "base_fcf_ttm": fcf_ttm,
            "fcf_yield": round(fcf_yield, 4) if fcf_yield is not None else None,
            "dcf_fair_value": round(dcf_value, 2) if dcf_value is not None else None,
            "growth_rate": round(growth, 4),
            "growth_source": fundamentals.get("growth_estimate", {}).get("source"),
            "discount_rate": round(rate, 4),
            "terminal_growth": round(terminal_growth, 4),
            "risk_free": round(rf, 4),
            "beta": fundamentals.get("beta"),
            "shares_outstanding": shares,
            "forecast_years": config.FORECAST_YEARS,
        },
        "analyst": fundamentals.get("analyst", {}),
        "history": {
            "prices": prices["prices"],
            # The historical line only makes sense for the DCF method; an
            # analyst-target fair value has no free history, so it plots as
            # a single present-day point.
            "fair_values": (
                fair_value_history(fundamentals, growth, terminal_growth, rate, fair_value)
                if method == "dcf"
                else [[str(date.today()), round(fair_value, 2)]] if fair_value else []
            ),
        },
    }


def fair_value_history(
    fundamentals: dict,
    growth: float,
    terminal_growth: float,
    rate: float,
    current_fair_value: float | None,
) -> list[list]:
    """Fair value at past fiscal year-ends, using each year's reported FCF
    and that year's diluted share count.

    Today's growth/discount assumptions are held constant across history —
    an approximation (point-in-time estimates aren't free), disclosed in
    the UI. It still shows the essential story: how the value of the
    business moved against its price.
    """
    shares_by_year = fundamentals.get("shares_by_year", {})
    current_shares = fundamentals.get("shares_outstanding")
    points: list[list] = []
    for year_end, fcf in sorted(fundamentals.get("annual_fcf", {}).items()):
        shares = shares_by_year.get(year_end) or current_shares
        if not shares:
            continue
        fv = dcf_fair_value(
            DcfInputs(fcf, growth, terminal_growth, rate, shares)
        )
        if fv is not None:
            points.append([year_end, round(fv, 2)])
    if current_fair_value is not None:
        points.append([str(date.today()), round(current_fair_value, 2)])
    return points
