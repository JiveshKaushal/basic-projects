"""Futures analytics: basis, cost of carry, fair value and OI buildup."""
import math
from dataclasses import dataclass

from .config import DAYS_IN_YEAR


@dataclass
class FuturesView:
    spot: float
    future: float
    days: float
    basis: float
    basis_pct: float
    implied_carry: float     # annualised, decimal
    fair_value: float
    premium_to_fair: float


def analyze_basis(spot: float, future: float, days: float, rate: float, div_yield: float = 0.0) -> FuturesView:
    T = max(days, 0.5) / DAYS_IN_YEAR
    fair = spot * math.exp((rate - div_yield) * T)
    return FuturesView(
        spot=spot,
        future=future,
        days=days,
        basis=future - spot,
        basis_pct=(future / spot - 1) * 100,
        implied_carry=math.log(future / spot) / T,
        fair_value=fair,
        premium_to_fair=future - fair,
    )


BUILDUP = {
    (1, 1): ("Long buildup", "Price up with rising OI: fresh longs entering — bullish."),
    (-1, 1): ("Short buildup", "Price down with rising OI: fresh shorts entering — bearish."),
    (1, -1): ("Short covering", "Price up with falling OI: shorts exiting — bullish but may fade."),
    (-1, -1): ("Long unwinding", "Price down with falling OI: longs exiting — bearish but may fade."),
}


def classify_buildup(price_change: float, oi_change: float):
    """Classic price-vs-OI interpretation used on Indian F&O desks."""
    if price_change == 0 or oi_change == 0:
        return ("Neutral", "No clear change in price or open interest.")
    return BUILDUP[(1 if price_change > 0 else -1, 1 if oi_change > 0 else -1)]
