"""Historical implied-volatility context: IV percentile and IV rank.

* IV percentile = share of days in the look-back window on which IV was BELOW today's.
  (IVP 80 = IV was lower than today on 80% of days.)
* IV rank = where today's IV sits between the window's low (0) and high (100).

History sources:
* India VIX (NSE's 30-day implied volatility of NIFTY) — the standard proxy for index IV.
  Parsed from NSE's VIX history JSON/CSV download or fetched live.
* ATM IV snapshots the dashboard records each time a chain is analysed (any symbol).
"""
import csv
import io
import json
import math
import random
from datetime import date, datetime, timedelta
from typing import Iterable, List, Optional, Sequence, Tuple

Series = List[Tuple[date, float]]  # (day, IV in percent points, e.g. 14.2)

_DATE_FORMATS = ("%d-%b-%Y", "%d-%b-%y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d %b %Y", "%b %d, %Y")


def parse_day(s) -> date:
    if isinstance(s, date):
        return s
    t = str(s).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(t.title() if "%b" in fmt else t, fmt).date()
        except ValueError:
            pass
    # ISO timestamps like 2026-11-25T10:00:00
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00")).date()
    except ValueError:
        raise ValueError(f"Unrecognised date {s!r}")


def _clean(series: Iterable[Tuple[object, object]]) -> Series:
    """Parse, drop bad rows, keep one value per day (last wins), sort by date."""
    by_day = {}
    for d, v in series:
        try:
            day, val = parse_day(d), float(str(v).replace(",", ""))
        except (ValueError, TypeError):
            continue
        if math.isfinite(val) and 0 < val < 300:
            by_day[day] = val
    return sorted(by_day.items())


def _pick(keys: Sequence[str], *needles: str) -> Optional[str]:
    low = {k: k.strip().lower() for k in keys}
    for n in needles:
        for k, l in low.items():
            if l == n:
                return k
    for n in needles:
        for k, l in low.items():
            if n in l:
                return k
    return None


def parse_csv(text: str) -> Series:
    """NSE India VIX history CSV (Date, Open, High, Low, Close, ...) or any CSV with a
    date column and a value column named close / iv / vix / value."""
    rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
    if not rows:
        raise ValueError("CSV is empty")
    keys = list(rows[0].keys())
    dk = _pick(keys, "date", "timestamp", "day")
    vk = _pick(keys, "close", "atm_iv", "iv", "vix", "value")
    if not dk or not vk:
        raise ValueError(f"CSV needs a date column and a close/iv/vix column (found: {', '.join(k.strip() for k in keys)})")
    out = _clean((r.get(dk), r.get(vk)) for r in rows)
    if not out:
        raise ValueError("No valid rows in CSV")
    return out


def parse_nse_json(payload) -> Series:
    """NSE VIX history API JSON: {"data": [{"EOD_TIMESTAMP": "...", "EOD_CLOSE_INDEX_VAL": 14.2}, ...]}.
    Field names are matched loosely because NSE renames them from time to time."""
    if isinstance(payload, str):
        payload = json.loads(payload)
    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    if isinstance(data, dict):
        data = data.get("data") or []
    if not isinstance(data, list) or not data:
        raise ValueError("No VIX history rows in NSE response")
    keys = list(data[0].keys())
    dk = _pick(keys, "eod_timestamp", "timestamp", "date")
    vk = _pick(keys, "eod_close_index_val", "close_index_val", "close", "value")
    if not dk or not vk:
        raise ValueError(f"Unexpected VIX history fields: {', '.join(keys)}")
    out = _clean((r.get(dk), r.get(vk)) for r in data)
    if not out:
        raise ValueError("No valid rows in NSE VIX history")
    return out


def iv_stats(series: Series, current: Optional[float] = None, as_of: Optional[date] = None,
             lookback_days: int = 365) -> dict:
    """IV percentile/rank of `current` (default: latest value) against the look-back window."""
    if not series:
        raise ValueError("No IV history")
    as_of = as_of or series[-1][0]
    start = as_of - timedelta(days=lookback_days)
    window = [(d, v) for d, v in series if start <= d <= as_of]
    if current is None:
        if not window:
            raise ValueError("No IV history inside the look-back window")
        current = window[-1][1]
    past = [v for d, v in window if d < as_of] or [v for _, v in window]
    if len(past) < 2:
        raise ValueError("Need at least 2 days of IV history")
    lo, hi = min(past + [current]), max(past + [current])
    below = sum(1 for v in past if v < current)
    pct = 100.0 * below / len(past)
    rank = 100.0 * (current - lo) / (hi - lo) if hi > lo else 50.0
    mean = sum(past) / len(past)
    return {
        "current": current,
        "percentile": pct,
        "rank": rank,
        "low": lo,
        "high": hi,
        "mean": mean,
        "median": sorted(past)[len(past) // 2],
        "days": len(past),
        "start": window[0][0].isoformat() if window else None,
        "end": as_of.isoformat(),
        "regime": regime(pct),
        "read": interpret(pct, current, mean),
    }


def regime(percentile: float) -> str:
    if percentile >= 80:
        return "Very high"
    if percentile >= 60:
        return "High"
    if percentile > 40:
        return "Normal"
    if percentile > 20:
        return "Low"
    return "Very low"


def interpret(percentile: float, current: float, mean: float) -> str:
    base = (f"IV {current:.1f} is above {percentile:.0f}% of readings in the look-back window "
            f"(average {mean:.1f}). ")
    if percentile >= 80:
        return base + ("Options are expensive by recent standards: premium-selling structures "
                       "(credit spreads, iron condors) collect more, but high IV usually comes "
                       "with big moves — keep losses defined.")
    if percentile >= 60:
        return base + "Options are on the rich side; defined-risk credit strategies get better pricing."
    if percentile > 40:
        return base + "IV is in its normal range — no strong edge from volatility alone."
    if percentile > 20:
        return base + "Options are fairly cheap; debit spreads and long options cost less than usual."
    return base + ("Options are cheap by recent standards: buying premium (long options, debit "
                   "spreads, calendars) is relatively inexpensive, but low IV can persist and "
                   "short-premium trades collect little for the risk.")


def sample_history(current: float, as_of: Optional[date] = None, days: int = 365, seed: int = 5) -> Series:
    """Synthetic India-VIX-like history (mean-reverting) ending at `current`. NOT real data."""
    rng = random.Random(seed)
    as_of = as_of or date.today()
    out, v, d = [], 14.0, as_of - timedelta(days=days)
    while d <= as_of:
        if d.weekday() < 5:
            v += 0.06 * (14.0 - v) + rng.gauss(0, 0.8) + (rng.random() < 0.015) * rng.uniform(3, 7)
            v = min(max(v, 9.5), 32.0)
            out.append((d, round(v, 2)))
        d += timedelta(days=1)
    out[-1] = (out[-1][0], round(current, 2))
    return out


def series_json(series: Series) -> list:
    return [[d.isoformat(), v] for d, v in series]


# ---- live fetch (local server mode) --------------------------------------------

def fetch_nse_vix(days: int = 365, timeout: int = 15) -> Series:
    """Best-effort India VIX history from nseindia.com (needs a browser-like session)."""
    import urllib.request
    from http.cookiejar import CookieJar

    from .chain import _UA

    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
    headers = {"User-Agent": _UA, "Accept": "application/json, text/plain, */*",
               "Referer": "https://www.nseindia.com/reports-indices-historical-vix"}

    def get(url):
        with opener.open(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
            return r.read()

    get("https://www.nseindia.com/reports-indices-historical-vix")
    end = date.today()
    rows: Series = []
    # NSE limits the range per request, so fetch in ~90-day chunks.
    chunk_end = end
    while chunk_end > end - timedelta(days=days):
        chunk_start = max(chunk_end - timedelta(days=89), end - timedelta(days=days))
        url = ("https://www.nseindia.com/api/historical/vixhistory?from="
               f"{chunk_start:%d-%m-%Y}&to={chunk_end:%d-%m-%Y}")
        rows += parse_nse_json(json.loads(get(url)))
        chunk_end = chunk_start - timedelta(days=1)
    return _clean(rows)
