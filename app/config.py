"""Environment-driven configuration.

Every knob is a FAIMAR_* env var so local runs and hosted deployments
configure the same way (12-factor style, no config files to migrate).
"""

import os
from pathlib import Path


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return float(raw)


# Where the SQLite cache lives. Point at a mounted volume when hosted.
CACHE_PATH = Path(os.environ.get("FAIMAR_CACHE_PATH", "cache.db"))

# Cache TTLs (seconds). Fundamentals move slowly; quotes move fast.
TTL_FUNDAMENTALS = _env_float("FAIMAR_TTL_FUNDAMENTALS", 24 * 3600)
TTL_PRICES = _env_float("FAIMAR_TTL_PRICES", 30 * 60)
TTL_RISK_FREE = _env_float("FAIMAR_TTL_RISK_FREE", 12 * 3600)

# Valuation model parameters.
EQUITY_RISK_PREMIUM = _env_float("FAIMAR_EQUITY_RISK_PREMIUM", 0.05)
DEFAULT_RISK_FREE = _env_float("FAIMAR_DEFAULT_RISK_FREE", 0.045)
TERMINAL_GROWTH_CAP = _env_float("FAIMAR_TERMINAL_GROWTH_CAP", 0.03)
GROWTH_FLOOR = _env_float("FAIMAR_GROWTH_FLOOR", -0.20)
GROWTH_CAP = _env_float("FAIMAR_GROWTH_CAP", 0.25)
BETA_FLOOR = _env_float("FAIMAR_BETA_FLOOR", 0.8)
BETA_CAP = _env_float("FAIMAR_BETA_CAP", 2.0)
DISCOUNT_FLOOR = _env_float("FAIMAR_DISCOUNT_FLOOR", 0.06)
DISCOUNT_CAP = _env_float("FAIMAR_DISCOUNT_CAP", 0.15)

# Forecast horizon: explicit growth fades linearly to terminal over N years.
FORECAST_YEARS = int(_env_float("FAIMAR_FORECAST_YEARS", 10))

# Below this FCF yield (TTM FCF / market cap) a trailing-FCF DCF says more
# about the model than the company; prefer the analyst consensus instead.
MIN_FCF_YIELD = _env_float("FAIMAR_MIN_FCF_YIELD", 0.01)
