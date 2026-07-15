"""Nasdaq public site API — free historical analyst consensus targets.

api.nasdaq.com backs nasdaq.com's own analyst-research pages and returns
roughly a year of *monthly* consensus price-target history, which is the
closest free equivalent to the stepped "fair value" revision history the
paid platforms chart. Unofficial like Yahoo's endpoints, so failures
degrade to an empty history rather than breaking the valuation.
"""

import json
import urllib.request
from datetime import datetime, timezone

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def fetch_target_history(symbol: str) -> dict:
    url = f"https://api.nasdaq.com/api/analyst/{symbol.lower()}/targetprice"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.load(resp)

    payload = data.get("data") or {}
    points: list[list] = []
    for row in payload.get("historicalConsensus") or []:
        epoch, value = row.get("x"), row.get("y")
        if not epoch or not value:
            continue
        day = datetime.fromtimestamp(epoch, tz=timezone.utc).date().isoformat()
        points.append([day, round(float(value), 2)])
    points.sort()

    overview = payload.get("consensusOverview") or {}
    consensus = overview.get("priceTarget")
    return {
        "history": points,
        "consensus": round(float(consensus), 2) if consensus else None,
    }
