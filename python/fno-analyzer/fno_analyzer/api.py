"""JSON API functions shared by the local server (web.py) and the in-browser
GitHub Pages build (Pyodide). No networking or HTTP-server imports here except
the optional live NSE fetch."""
import json
import math

from .chain import OptionChain, fetch_nse, from_csv_text, from_nse_json
from .config import DAYS_IN_YEAR, DEFAULT_RISK_FREE_RATE, LOT_SIZES, lot_size
from .futures import analyze_basis, classify_buildup
from .insights import generate, strategy_hint
from .presets import build_presets
from .pricing import bs_price, greeks, implied_vol, prob_itm
from .sample import sample_chain
from .strategy import Leg, Strategy, analyze, parse_leg

DISCLAIMER = ("Educational tool only — not investment advice. Probabilities come from a lognormal "
              "model using implied volatility; real markets have fat tails, gaps and changing IV. "
              "SEBI studies show most individual F&O traders lose money.")


def _num(x):
    """JSON-safe number: inf/nan -> None."""
    if x is None:
        return None
    x = float(x)
    return x if math.isfinite(x) else None


def _f(params, key, default=None, cast=float):
    v = params.get(key)
    if v in (None, ""):
        return default
    return cast(v)


# ---- serialisation -----------------------------------------------------------

def payoff_curve(strategy: Strategy, spot: float, sigma: float, T: float, n: int = 160):
    span = max(2.5 * sigma * math.sqrt(T), 0.02)
    strikes = [l.strike for l in strategy.legs] or [spot]
    lo = min(spot * math.exp(-span), min(strikes) * 0.995)
    hi = max(spot * math.exp(span), max(strikes) * 1.005)
    xs = {lo + (hi - lo) * i / (n - 1) for i in range(n)}
    xs |= {l.strike for l in strategy.legs if lo < l.strike < hi}
    xs |= {b for b in strategy.breakevens(spot) if lo < b < hi}
    return [[round(x, 2), round(strategy.payoff(x), 2)] for x in sorted(xs)]


def report_json(rep, spot, sigma, T):
    s = rep.strategy
    return {
        "name": s.name,
        "legs": [{"kind": l.kind, "side": l.side, "strike": l.strike, "premium": l.premium,
                  "lots": l.lots, "text": l.describe()} for l in s.legs],
        "lot_size": s.lot_size,
        "net_premium": _num(rep.net_premium),
        "max_profit": _num(rep.max_profit),
        "max_loss": _num(rep.max_loss),
        "unlimited_profit": rep.max_profit == math.inf,
        "unlimited_loss": rep.max_loss == -math.inf,
        "breakevens": rep.breakevens,
        "pop": rep.pop,
        "expected_pnl": _num(rep.expected_pnl),
        "reward_risk": _num(rep.reward_risk),
        "greeks": {k: _num(v) for k, v in rep.greeks.items()},
        "curve": payoff_curve(s, spot, sigma, T),
    }


def chain_json(chain: OptionChain, lots: int, iv_override=None, sample=False):
    iv = iv_override or chain.atm_iv()
    if iv <= 0:
        raise ValueError("Could not determine ATM IV; enter a volatility override.")
    ins = generate(chain)
    reports = [analyze(s, chain.spot, iv, chain.T, chain.rate) for s in build_presets(chain, lots)]
    reports.sort(key=lambda r: r.pop, reverse=True)
    c_oi, p_oi = chain.total_oi()
    em1, em2 = chain.spot * iv * math.sqrt(chain.T), 2 * chain.spot * iv * math.sqrt(chain.T)
    return {
        "symbol": chain.symbol,
        "sample": sample,
        "spot": chain.spot,
        "expiry": chain.expiry.isoformat(),
        "as_of": chain.as_of.isoformat(),
        "days": chain.days_to_expiry - 0.5,
        "T": chain.T,
        "rate": chain.rate,
        "lot_size": lots,
        "atm": chain.atm_strike(),
        "step": chain.strike_step,
        "atm_iv": iv,
        "pcr_oi": _num(chain.pcr_oi()),
        "pcr_volume": _num(chain.pcr_volume()),
        "pcr_oi_change": _num(chain.pcr_oi_change()),
        "max_pain": chain.max_pain(),
        "support": chain.support(),
        "resistance": chain.resistance(),
        "total_call_oi": c_oi,
        "total_put_oi": p_oi,
        "straddle": chain.straddle_price(),
        "skew": _num(chain.iv_skew()),
        "range_1sd": [chain.spot - em1, chain.spot + em1],
        "range_2sd": [chain.spot - em2, chain.spot + em2],
        "bias": ins.bias,
        "score": ins.score,
        "insights": ins.points,
        "hint": strategy_hint(ins, iv),
        "rows": [{
            "strike": r.strike,
            "call": vars(r.call), "put": vars(r.put),
        } for r in chain.rows],
        "strategies": [report_json(r, chain.spot, iv, chain.T) for r in reports],
        "disclaimer": DISCLAIMER,
    }


# ---- API handlers --------------------------------------------------------------

def api_analyze(p: dict):
    source = (p.get("source") or "sample").lower()
    symbol = (p.get("symbol") or "NIFTY").upper()
    rate = _f(p, "rate", DEFAULT_RISK_FREE_RATE)
    expiry = p.get("expiry") or None
    if source == "sample":
        chain = sample_chain(symbol, days=_f(p, "days", 6, int))
    elif source == "live":
        chain = fetch_nse(symbol, expiry, rate=rate)
    elif source == "csv":
        if not p.get("csv"):
            raise ValueError("Choose a CSV file.")
        spot = _f(p, "spot")
        if not spot or not expiry:
            raise ValueError("CSV needs spot price and expiry date.")
        chain = from_csv_text(p["csv"], symbol, spot, expiry, p.get("as_of") or None, rate)
    elif source == "json":
        data = p.get("json")
        if isinstance(data, str):
            data = json.loads(data)
        if not data:
            raise ValueError("Choose a saved NSE JSON file.")
        chain = from_nse_json(data, symbol, expiry, rate)
    else:
        raise ValueError(f"Unknown source {source!r}")
    lots = _f(p, "lot_size", None, int) or lot_size(chain.symbol)
    iv = _f(p, "iv")
    return chain_json(chain, lots, iv / 100 if iv else None, sample=source == "sample")


def api_strategy(p: dict):
    spot, iv, days = _f(p, "spot"), _f(p, "iv"), _f(p, "days")
    if not spot or not iv or days is None:
        raise ValueError("Spot, IV and days to expiry are required.")
    legs = []
    for l in p.get("legs") or []:
        if isinstance(l, str):
            legs.append(parse_leg(l))
        else:
            kind = {"ce": "call", "pe": "put", "fut": "future"}.get(str(l["kind"]).lower(), l["kind"])
            legs.append(Leg(kind, 1 if int(l["side"]) > 0 else -1, float(l["strike"]),
                            float(l.get("premium") or 0), int(l.get("lots") or 1)))
    if not legs:
        raise ValueError("Add at least one leg.")
    sigma, T = iv / 100, (days + 0.5) / DAYS_IN_YEAR
    for l in legs:
        l.iv = sigma
    lots = _f(p, "lot_size", None, int) or lot_size(p.get("symbol") or "NIFTY")
    strat = Strategy(p.get("name") or "Custom strategy", legs, lots)
    rep = analyze(strat, spot, sigma, T, _f(p, "rate", DEFAULT_RISK_FREE_RATE))
    out = report_json(rep, spot, sigma, T)
    out.update(spot=spot, atm_iv=sigma, T=T,
               range_1sd=[spot * (1 - sigma * math.sqrt(T)), spot * (1 + sigma * math.sqrt(T))])
    return out


def api_futures(p: dict):
    spot, fut, days = _f(p, "spot"), _f(p, "future"), _f(p, "days")
    if not spot or not fut or days is None:
        raise ValueError("Spot, future price and days to expiry are required.")
    rate = _f(p, "rate", DEFAULT_RISK_FREE_RATE)
    v = analyze_basis(spot, fut, days, rate, _f(p, "div", 1.2) / 100)
    if v.implied_carry > rate + 0.02:
        read = "Rich premium — aggressive long positioning / bullish sentiment."
    elif v.implied_carry < rate - 0.02:
        read = "Thin or negative carry — short positioning or dividend effect; bearish tilt."
    else:
        read = "Carry is near the risk-free rate — neutral."
    out = {k: _num(x) for k, x in vars(v).items()}
    out["read"] = read
    pc, oc = _f(p, "price_change"), _f(p, "oi_change")
    if pc is not None and oc is not None:
        out["buildup"], out["buildup_desc"] = classify_buildup(pc, oc)
    lots = _f(p, "lot_size", None, int) or lot_size(p.get("symbol") or "NIFTY")
    out["lot_size"] = lots
    out["notional"] = fut * lots
    return out


def api_price(p: dict):
    spot, strike, days = _f(p, "spot"), _f(p, "strike"), _f(p, "days")
    kind = p.get("type") or "call"
    rate = _f(p, "rate", DEFAULT_RISK_FREE_RATE)
    T = (days + 0.5) / DAYS_IN_YEAR
    premium, iv = _f(p, "premium"), _f(p, "iv")
    if iv:
        sigma = iv / 100
    elif premium:
        sigma = implied_vol(premium, spot, strike, T, rate, kind)
        if sigma is None:
            raise ValueError("No implied volatility matches that premium.")
    else:
        raise ValueError("Enter IV or market premium.")
    return {
        "iv": sigma,
        "price": bs_price(spot, strike, T, rate, sigma, kind),
        "greeks": greeks(spot, strike, T, rate, sigma, kind),
        "prob_itm": prob_itm(spot, strike, T, rate, sigma, kind),
    }


def api_ivhistory(p: dict):
    """IV percentile / rank from a history source.

    source: sample | live (NSE India VIX, local server only) | csv | json | series
    series: [[YYYY-MM-DD, iv_percent], ...] (e.g. the dashboard's recorded ATM IV)
    current: optional IV in percent points to rank (default: latest history value)
    """
    from datetime import date, timedelta
    from . import ivhistory as ivh

    source = (p.get("source") or "sample").lower()
    lookback = _f(p, "lookback", 365, int)
    current = _f(p, "current")
    as_of = ivh.parse_day(p["as_of"]) if p.get("as_of") else None
    basis = "India VIX"
    if source == "sample":
        series = ivh.sample_history(current or 13.0, as_of or date.today())
        basis = "Sample VIX-like history (synthetic)"
    elif source == "live":
        series = ivh.fetch_nse_vix(lookback)
    elif source == "csv":
        if not p.get("csv"):
            raise ValueError("Choose a VIX history CSV file.")
        series = ivh.parse_csv(p["csv"])
        basis = p.get("basis") or "Uploaded history"
    elif source == "json":
        if not p.get("json"):
            raise ValueError("No VIX history data.")
        series = ivh.parse_nse_json(p["json"])
    elif source == "series":
        series = ivh._clean(tuple(x) for x in (p.get("series") or []))
        basis = p.get("basis") or "Recorded ATM IV"
    else:
        raise ValueError(f"Unknown IV history source {source!r}")
    stats = ivh.iv_stats(series, current, as_of, lookback)
    start = ivh.parse_day(stats["end"]) - timedelta(days=lookback)
    stats["series"] = ivh.series_json([(d, v) for d, v in series if d >= start])
    stats["basis"] = basis
    return stats


ROUTES = {
    "/api/analyze": api_analyze,
    "/api/strategy": api_strategy,
    "/api/futures": api_futures,
    "/api/price": api_price,
    "/api/ivhistory": api_ivhistory,
}


def call(path: str, params_json: str) -> str:
    """Entry point for the browser build: JSON string in, JSON string out."""
    try:
        return json.dumps({"ok": True, "data": ROUTES[path](json.loads(params_json))}, allow_nan=False)
    except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
        return json.dumps({"ok": False, "error": str(e)})
