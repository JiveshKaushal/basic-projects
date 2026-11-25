"""Local web dashboard: a small JSON API over the analyzer plus a static page.

    python3 -m fno_analyzer serve            # http://127.0.0.1:8000
    python3 -m fno_analyzer serve --port 8080 --open

Standard library only. Binds to localhost by default — it is a personal tool,
not something to expose on the internet.
"""
import json
import math
import os
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import __version__
from .chain import OptionChain, fetch_nse, from_csv_text, from_nse_json
from .config import DAYS_IN_YEAR, DEFAULT_RISK_FREE_RATE, LOT_SIZES, lot_size
from .futures import analyze_basis, classify_buildup
from .insights import generate, strategy_hint
from .presets import build_presets
from .pricing import bs_price, greeks, implied_vol, prob_itm
from .sample import sample_chain
from .strategy import Leg, Strategy, analyze, parse_leg

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
MAX_BODY = 5 * 1024 * 1024

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


ROUTES = {
    "/api/analyze": api_analyze,
    "/api/strategy": api_strategy,
    "/api/futures": api_futures,
    "/api/price": api_price,
}


class Handler(BaseHTTPRequestHandler):
    server_version = f"FnoAnalyzer/{__version__}"

    def log_message(self, fmt, *args):  # quieter console
        if getattr(self.server, "verbose", False):
            super().log_message(fmt, *args)

    def _send(self, code, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, allow_nan=False).encode(), "application/json; charset=utf-8")

    def _api(self, path, params):
        try:
            self._json(200, ROUTES[path](params))
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
            self._json(400, {"error": str(e)})
        except Exception as e:  # pragma: no cover
            traceback.print_exc()
            self._json(500, {"error": f"Internal error: {e}"})

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ROUTES:
            params = {k: v[-1] for k, v in parse_qs(url.query).items()}
            return self._api(url.path, params)
        if url.path == "/api/meta":
            return self._json(200, {"version": __version__, "lot_sizes": LOT_SIZES,
                                    "rate": DEFAULT_RISK_FREE_RATE, "disclaimer": DISCLAIMER})
        files = {"/": ("index.html", "text/html; charset=utf-8"),
                 "/index.html": ("index.html", "text/html; charset=utf-8")}
        if url.path not in files:
            return self._send(404, b"Not found", "text/plain")
        name, ctype = files[url.path]
        with open(os.path.join(STATIC_DIR, name), "rb") as fh:
            self._send(200, fh.read(), ctype)

    def do_POST(self):
        url = urlparse(self.path)
        if url.path not in ROUTES:
            return self._json(404, {"error": "Not found"})
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._json(413, {"error": "Upload too large (max 5 MB)"})
        try:
            params = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "Body must be JSON"})
        self._api(url.path, params)


def serve(host: str = "127.0.0.1", port: int = 8000, open_browser: bool = False, verbose: bool = False):
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.verbose = verbose
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{httpd.server_address[1]}/"
    print(f"F&O Analyzer dashboard running at {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
