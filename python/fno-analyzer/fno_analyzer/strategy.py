"""Strategy payoff, breakevens, probability of profit (POP) and expected P&L.

Payoffs at expiry are piecewise-linear in the underlying price, with kinks only at
strikes, so breakevens and max profit/loss are computed exactly (no grid search).

POP assumes the underlying at expiry is lognormally distributed with volatility
`sigma` (normally the ATM implied volatility). This is a model estimate: real
returns have fatter tails and the volatility smile means OTM options are priced
with higher IVs than ATM.
"""
import math
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .pricing import bs_price, greeks, norm_cdf


@dataclass
class Leg:
    kind: str            # "call", "put" or "future"
    side: int            # +1 buy, -1 sell
    strike: float        # entry price for futures
    premium: float = 0.0 # per unit; 0 for futures
    lots: int = 1
    iv: float = 0.0      # optional per-leg IV (for Greeks)

    def payoff(self, S: float) -> float:
        """P&L per unit at expiry (premium included)."""
        if self.kind == "call":
            v = max(S - self.strike, 0.0) - self.premium
        elif self.kind == "put":
            v = max(self.strike - S, 0.0) - self.premium
        else:
            v = S - self.strike
        return self.side * self.lots * v

    def describe(self) -> str:
        act = "BUY " if self.side > 0 else "SELL"
        if self.kind == "future":
            return f"{act} {self.lots}x FUT @ {self.strike:g}"
        k = "CE" if self.kind == "call" else "PE"
        return f"{act} {self.lots}x {self.strike:g} {k} @ {self.premium:.2f}"


@dataclass
class Strategy:
    name: str
    legs: List[Leg]
    lot_size: int = 1

    def payoff(self, S: float) -> float:
        """Total P&L in rupees at expiry."""
        return sum(l.payoff(S) for l in self.legs) * self.lot_size

    def net_premium(self) -> float:
        """Positive = credit received, negative = debit paid (rupees)."""
        return -sum(l.side * l.lots * l.premium for l in self.legs if l.kind != "future") * self.lot_size

    def _breakpoints(self, spot: float) -> List[float]:
        pts = {0.0, *(l.strike for l in self.legs)}
        hi = max(max(pts), spot) * 4
        pts.add(hi)
        return sorted(pts)

    def upside_slope(self) -> float:
        return sum(l.side * l.lots for l in self.legs if l.kind in ("call", "future")) * self.lot_size

    def breakevens(self, spot: float) -> List[float]:
        pts = self._breakpoints(spot)
        out = []
        for a, b in zip(pts, pts[1:]):
            pa, pb = self.payoff(a), self.payoff(b)
            if pa == 0 and a > 0:
                out.append(a)
            elif pa * pb < 0:
                out.append(a + (b - a) * (-pa) / (pb - pa))
        # beyond last breakpoint the payoff is linear with upside_slope
        last = pts[-1]
        pl, slope = self.payoff(last), self.upside_slope()
        if slope and pl * slope < 0:
            out.append(last - pl / slope)
        return [round(x, 2) for x in sorted(set(out)) if x > 0]

    def profit_intervals(self, spot: float) -> List[Tuple[float, float]]:
        """Price intervals at expiry where P&L > 0."""
        edges = [0.0] + self.breakevens(spot) + [math.inf]
        out = []
        for a, b in zip(edges, edges[1:]):
            mid = (a + b) / 2 if b != math.inf else a * 2 + 1
            if self.payoff(mid) > 0:
                out.append((a, b))
        return out

    def max_profit_loss(self, spot: float):
        pts = self._breakpoints(spot)
        vals = [self.payoff(p) for p in pts]
        slope = self.upside_slope()
        max_p = math.inf if slope > 0 else max(vals)
        max_l = -math.inf if slope < 0 else min(vals)
        return max_p, max_l


def lognormal_cdf(x: float, spot: float, sigma: float, T: float, mu: float = 0.0) -> float:
    if x <= 0:
        return 0.0
    if x == math.inf:
        return 1.0
    s = sigma * math.sqrt(T)
    return norm_cdf((math.log(x / spot) - (mu - 0.5 * sigma ** 2) * T) / s)


def probability_of_profit(strategy: Strategy, spot: float, sigma: float, T: float, mu: float = 0.0) -> float:
    return sum(lognormal_cdf(b, spot, sigma, T, mu) - lognormal_cdf(a, spot, sigma, T, mu)
               for a, b in strategy.profit_intervals(spot))


def expected_pnl(strategy: Strategy, spot: float, sigma: float, T: float, mu: float = 0.0, n: int = 4001) -> float:
    """Expected P&L at expiry under the lognormal model (numerical integration)."""
    s = sigma * math.sqrt(T)
    m = (mu - 0.5 * sigma ** 2) * T
    lo, hi = -8.0, 8.0
    h = (hi - lo) / (n - 1)
    total = 0.0
    for i in range(n):
        z = lo + i * h
        w = 0.5 if i in (0, n - 1) else 1.0
        total += w * strategy.payoff(spot * math.exp(m + s * z)) * math.exp(-0.5 * z * z)
    return total * h / math.sqrt(2 * math.pi)


def strategy_greeks(strategy: Strategy, spot: float, T: float, r: float, default_iv: float) -> dict:
    g = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    for l in strategy.legs:
        mult = l.side * l.lots * strategy.lot_size
        if l.kind == "future":
            g["delta"] += mult
            continue
        lg = greeks(spot, l.strike, T, r, l.iv or default_iv, l.kind)
        for k in g:
            g[k] += mult * lg[k]
    return g


@dataclass
class Report:
    strategy: Strategy
    net_premium: float
    max_profit: float
    max_loss: float
    breakevens: List[float]
    pop: float
    expected_pnl: float
    reward_risk: Optional[float]
    greeks: dict = field(default_factory=dict)


def analyze(strategy: Strategy, spot: float, sigma: float, T: float, r: float = 0.0,
            mu: Optional[float] = None) -> Report:
    """mu = drift used for POP. Default 0 (no directional view); pass r for risk-neutral."""
    mu = 0.0 if mu is None else mu
    max_p, max_l = strategy.max_profit_loss(spot)
    rr = None
    if math.isfinite(max_p) and math.isfinite(max_l) and max_l < 0:
        rr = max_p / -max_l
    return Report(
        strategy=strategy,
        net_premium=strategy.net_premium(),
        max_profit=max_p,
        max_loss=max_l,
        breakevens=strategy.breakevens(spot),
        pop=probability_of_profit(strategy, spot, sigma, T, mu),
        expected_pnl=expected_pnl(strategy, spot, sigma, T, mu),
        reward_risk=rr,
        greeks=strategy_greeks(strategy, spot, T, r, sigma),
    )


_LEG_RE = re.compile(
    r"^\s*(buy|sell|b|s)\s+(?:(\d+)\s*x\s*)?(ce|pe|call|put|fut|future)\s+([\d.]+)(?:\s*@\s*([\d.]+))?\s*$", re.I)


def parse_leg(text: str) -> Leg:
    """Parse e.g. 'BUY CE 24000 @ 120', 'sell 2x PE 23500@80', 'buy FUT 24100'."""
    m = _LEG_RE.match(text)
    if not m:
        raise ValueError(f"Can't parse leg {text!r}. Format: 'BUY CE 24000 @ 120'")
    side = 1 if m.group(1).lower().startswith("b") else -1
    lots = int(m.group(2) or 1)
    k = m.group(3).lower()
    kind = "call" if k in ("ce", "call") else "put" if k in ("pe", "put") else "future"
    price = float(m.group(4))
    prem = float(m.group(5) or 0)
    if kind != "future" and m.group(5) is None:
        raise ValueError(f"Option leg needs a premium: {text!r}")
    return Leg(kind, side, price, prem, lots)


def theoretical_premium(kind, spot, strike, T, r, iv):
    return bs_price(spot, strike, T, r, iv, kind)
