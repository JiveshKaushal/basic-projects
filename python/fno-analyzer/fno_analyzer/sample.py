"""Synthetic option chain for demos and tests. NOT real market data."""
import math
import random
from datetime import date, timedelta

from .chain import OptionChain, Quote, StrikeRow
from .config import DEFAULT_RISK_FREE_RATE, STRIKE_STEPS
from .pricing import bs_price

SAMPLE_SPOTS = {"NIFTY": 24350.0, "BANKNIFTY": 52400.0, "FINNIFTY": 23500.0,
                "MIDCPNIFTY": 12600.0, "SENSEX": 80100.0}


def sample_chain(symbol: str = "NIFTY", days: int = 6, seed: int = 7,
                 as_of: date = None) -> OptionChain:
    sym = symbol.upper()
    rng = random.Random(seed)
    spot = SAMPLE_SPOTS.get(sym, 1000.0)
    step = STRIKE_STEPS.get(sym, max(round(spot * 0.005), 1))
    as_of = as_of or date.today()
    T = (days + 0.5) / 365
    r = DEFAULT_RISK_FREE_RATE
    atm = round(spot / step) * step
    rows = []
    for i in range(-30, 31):
        K = atm + i * step
        m = math.log(K / spot)
        iv = 0.125 - 0.30 * m + 3.0 * m * m          # put skew + smile
        roundness = 2.0 if K % (step * 10) == 0 else 1.3 if K % (step * 2) == 0 else 1.0
        dist = (K - spot) / (spot * 0.03)
        call_oi = roundness * 1e5 * math.exp(-((dist - 0.8) ** 2) / 1.2) * rng.uniform(0.8, 1.2)
        put_oi = roundness * 1.15e5 * math.exp(-((dist + 0.8) ** 2) / 1.2) * rng.uniform(0.8, 1.2)
        # puts usually trade a little richer than calls at the same strike
        quote = lambda kind, oi, v=iv: Quote(
            ltp=round(max(bs_price(spot, K, T, r, v + (0.0015 if kind == "put" else -0.0015), kind), 0.05), 2),
            iv=round(v + (0.0015 if kind == "put" else -0.0015), 4),
            oi=round(oi),
            oi_change=round(oi * rng.uniform(-0.15, 0.35)),
            volume=round(oi * rng.uniform(2, 6)),
        )
        rows.append(StrikeRow(float(K), quote("call", call_oi), quote("put", put_oi)))
    return OptionChain(sym, spot, as_of + timedelta(days=days), rows, as_of=as_of, rate=r)
