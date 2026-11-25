"""Option chain model, loaders (NSE JSON, CSV, live NSE) and chain analytics."""
import csv
import json
import math
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime
from http.cookiejar import CookieJar
from typing import List, Optional

from .config import DAYS_IN_YEAR, DEFAULT_RISK_FREE_RATE
from .pricing import implied_vol


@dataclass
class Quote:
    ltp: float = 0.0
    iv: float = 0.0          # decimal, e.g. 0.14 for 14%
    oi: float = 0.0
    oi_change: float = 0.0
    volume: float = 0.0


@dataclass
class StrikeRow:
    strike: float
    call: Quote = field(default_factory=Quote)
    put: Quote = field(default_factory=Quote)


@dataclass
class OptionChain:
    symbol: str
    spot: float
    expiry: date
    rows: List[StrikeRow]
    as_of: date = field(default_factory=date.today)
    rate: float = DEFAULT_RISK_FREE_RATE

    def __post_init__(self):
        self.rows.sort(key=lambda r: r.strike)
        self.fill_missing_iv()

    # ---- basic properties -------------------------------------------------
    @property
    def days_to_expiry(self) -> float:
        # Count expiry day as a partial day so T never hits zero on expiry morning.
        return max((self.expiry - self.as_of).days, 0) + 0.5

    @property
    def T(self) -> float:
        return self.days_to_expiry / DAYS_IN_YEAR

    @property
    def strikes(self) -> List[float]:
        return [r.strike for r in self.rows]

    @property
    def strike_step(self) -> float:
        s = self.strikes
        diffs = sorted(b - a for a, b in zip(s, s[1:]) if b > a)
        return diffs[len(diffs) // 2] if diffs else 1.0

    def row(self, strike: float) -> StrikeRow:
        return min(self.rows, key=lambda r: abs(r.strike - strike))

    def atm_strike(self) -> float:
        return self.row(self.spot).strike

    def nearest_strike(self, price: float) -> float:
        return self.row(price).strike

    def fill_missing_iv(self):
        for r in self.rows:
            for kind, q in (("call", r.call), ("put", r.put)):
                if q.iv <= 0 and q.ltp > 0:
                    iv = implied_vol(q.ltp, self.spot, r.strike, self.T, self.rate, kind)
                    q.iv = iv or 0.0

    # ---- analytics --------------------------------------------------------
    def atm_iv(self) -> float:
        """Average of call & put IV at the ATM strike (falls back to neighbours)."""
        atm = self.atm_strike()
        for r in sorted(self.rows, key=lambda r: abs(r.strike - atm)):
            ivs = [v for v in (r.call.iv, r.put.iv) if v > 0]
            if ivs:
                return sum(ivs) / len(ivs)
        return 0.0

    def total_oi(self):
        return sum(r.call.oi for r in self.rows), sum(r.put.oi for r in self.rows)

    def pcr_oi(self) -> float:
        c, p = self.total_oi()
        return p / c if c else float("nan")

    def pcr_volume(self) -> float:
        c = sum(r.call.volume for r in self.rows)
        p = sum(r.put.volume for r in self.rows)
        return p / c if c else float("nan")

    def pcr_oi_change(self) -> float:
        c = sum(r.call.oi_change for r in self.rows)
        p = sum(r.put.oi_change for r in self.rows)
        return p / c if c > 0 else float("nan")

    def max_pain(self) -> float:
        """Strike at which total intrinsic value paid to option buyers is minimal."""
        best, best_pain = None, math.inf
        for settle in self.strikes:
            pain = sum(
                r.call.oi * max(settle - r.strike, 0) + r.put.oi * max(r.strike - settle, 0)
                for r in self.rows
            )
            if pain < best_pain:
                best, best_pain = settle, pain
        return best

    def straddle_price(self) -> float:
        r = self.row(self.atm_strike())
        return r.call.ltp + r.put.ltp

    def expected_move(self, sd: float = 1.0) -> float:
        """One standard-deviation move to expiry implied by ATM IV."""
        return self.spot * self.atm_iv() * math.sqrt(self.T) * sd

    def top_oi(self, side: str, n: int = 3, key: str = "oi"):
        def val(r):
            return getattr(r.call if side == "call" else r.put, key)
        rows = sorted(self.rows, key=val, reverse=True)[:n]
        return [(r.strike, val(r)) for r in rows]

    def resistance(self) -> float:
        """Highest call OI above spot (call writers defend this level)."""
        above = [r for r in self.rows if r.strike >= self.spot] or self.rows
        return max(above, key=lambda r: r.call.oi).strike

    def support(self) -> float:
        """Highest put OI below spot (put writers defend this level)."""
        below = [r for r in self.rows if r.strike <= self.spot] or self.rows
        return max(below, key=lambda r: r.put.oi).strike

    def iv_skew(self) -> Optional[float]:
        """OTM put IV minus OTM call IV, about one expected move away from spot.

        Positive skew = market pays more for downside protection (normal for indices);
        a sharply rising skew signals fear.
        """
        em = self.expected_move()
        if em <= 0:
            return None
        p = self.row(self.spot - em).put.iv
        c = self.row(self.spot + em).call.iv
        if p <= 0 or c <= 0:
            return None
        return p - c


# ---- loaders ---------------------------------------------------------------

def _parse_date(s: str) -> date:
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d %b %Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Unrecognised date: {s!r} (use YYYY-MM-DD)")


def _q(d: Optional[dict]) -> Quote:
    if not d:
        return Quote()
    return Quote(
        ltp=float(d.get("lastPrice") or 0),
        iv=float(d.get("impliedVolatility") or 0) / 100.0,
        oi=float(d.get("openInterest") or 0),
        oi_change=float(d.get("changeinOpenInterest") or 0),
        volume=float(d.get("totalTradedVolume") or 0),
    )


def from_nse_json(payload: dict, symbol: str, expiry: Optional[str] = None,
                  rate: float = DEFAULT_RISK_FREE_RATE) -> OptionChain:
    """Build a chain from NSE's option-chain JSON (records.data[] with CE/PE)."""
    records = payload.get("records", payload)
    data = records.get("data") or payload.get("filtered", {}).get("data") or []
    if not data:
        raise ValueError("No option data found in NSE response")
    expiries = records.get("expiryDates") or sorted(
        {d.get("expiryDate") for d in data if d.get("expiryDate")}, key=_parse_date)
    exp_str = expiry or expiries[0]
    exp = _parse_date(exp_str)
    rows, spot = [], records.get("underlyingValue")
    for d in data:
        d_exp = d.get("expiryDate") or (d.get("CE") or d.get("PE") or {}).get("expiryDate")
        if d_exp and _parse_date(d_exp) != exp:
            continue
        rows.append(StrikeRow(float(d["strikePrice"]), _q(d.get("CE")), _q(d.get("PE"))))
        spot = spot or (d.get("CE") or d.get("PE") or {}).get("underlyingValue")
    if not rows or not spot:
        raise ValueError(f"No rows for expiry {exp_str}")
    as_of = date.today()
    ts = records.get("timestamp")
    if ts:
        try:
            as_of = datetime.strptime(ts, "%d-%b-%Y %H:%M:%S").date()
        except ValueError:
            pass
    return OptionChain(symbol.upper(), float(spot), exp, rows, as_of=as_of, rate=rate)


def from_csv(path: str, symbol: str, spot: float, expiry: str, as_of: Optional[str] = None,
             rate: float = DEFAULT_RISK_FREE_RATE) -> OptionChain:
    """Load a chain from CSV with header:

    strike,call_ltp,call_iv,call_oi,call_oi_change,call_volume,put_ltp,put_iv,put_oi,put_oi_change,put_volume

    IV in percent (e.g. 13.5). Missing IV columns are back-solved from LTP.
    """
    def f(row, k):
        v = (row.get(k) or "").replace(",", "").strip()
        return float(v) if v not in ("", "-") else 0.0

    rows = []
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            rows.append(StrikeRow(
                f(row, "strike"),
                Quote(f(row, "call_ltp"), f(row, "call_iv") / 100, f(row, "call_oi"),
                      f(row, "call_oi_change"), f(row, "call_volume")),
                Quote(f(row, "put_ltp"), f(row, "put_iv") / 100, f(row, "put_oi"),
                      f(row, "put_oi_change"), f(row, "put_volume")),
            ))
    return OptionChain(symbol.upper(), spot, _parse_date(expiry), rows,
                       as_of=_parse_date(as_of) if as_of else date.today(), rate=rate)


def from_json_file(path: str, symbol: str, expiry: Optional[str] = None,
                   rate: float = DEFAULT_RISK_FREE_RATE) -> OptionChain:
    with open(path) as fh:
        return from_nse_json(json.load(fh), symbol, expiry, rate)


_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
INDICES = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}


def fetch_nse(symbol: str, expiry: Optional[str] = None, timeout: int = 15,
              rate: float = DEFAULT_RISK_FREE_RATE) -> OptionChain:
    """Best-effort live fetch from nseindia.com.

    NSE's site needs session cookies, may block non-browser or cloud traffic, and
    changes its API occasionally. If this fails, save the JSON from your browser
    (or export a CSV) and use --json / --csv instead.
    """
    sym = symbol.upper()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
    headers = {"User-Agent": _UA, "Accept": "application/json, text/plain, */*",
               "Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.nseindia.com/option-chain"}

    def get(url):
        req = urllib.request.Request(url, headers=headers)
        with opener.open(req, timeout=timeout) as resp:
            return resp.read()

    get("https://www.nseindia.com/option-chain")  # sets cookies
    kind = "indices" if sym in INDICES else "equities"
    errors = []
    urls = [f"https://www.nseindia.com/api/option-chain-{kind}?symbol={sym}"]
    try:
        info = json.loads(get(f"https://www.nseindia.com/api/option-chain-contract-info?symbol={sym}"))
        exp = expiry or (info.get("expiryDates") or [None])[0]
        if exp:
            typ = "Indices" if kind == "indices" else "Equity"
            urls.insert(0, f"https://www.nseindia.com/api/option-chain-v3?type={typ}"
                           f"&symbol={sym}&expiry={exp}")
            expiry = exp
    except Exception as e:  # older API without contract-info
        errors.append(str(e))
    for url in urls:
        try:
            payload = json.loads(get(url))
            return from_nse_json(payload, sym, expiry, rate)
        except Exception as e:
            errors.append(f"{url}: {e}")
    raise RuntimeError("Could not fetch live NSE data:\n  " + "\n  ".join(errors))
