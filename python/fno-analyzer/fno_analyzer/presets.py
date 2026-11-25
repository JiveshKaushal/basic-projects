"""Common strategies built automatically from an option chain."""
from typing import List

from .chain import OptionChain
from .strategy import Leg, Strategy


def _leg(chain: OptionChain, kind: str, side: int, strike: float) -> Leg:
    row = chain.row(strike)
    q = row.call if kind == "call" else row.put
    return Leg(kind, side, row.strike, q.ltp, 1, q.iv)


def build_presets(chain: OptionChain, lot_size: int) -> List[Strategy]:
    """Standard strategies with wings placed about one expected move from spot."""
    atm = chain.atm_strike()
    step = chain.strike_step
    em = chain.expected_move()
    up = chain.nearest_strike(chain.spot + em)
    dn = chain.nearest_strike(chain.spot - em)
    if up <= atm:
        up = atm + step
    if dn >= atm:
        dn = atm - step
    wing = max(step, round(em / 2 / step) * step)
    half_up = chain.nearest_strike(atm + wing)
    half_dn = chain.nearest_strike(atm - wing)

    specs = [
        ("Long Call (ATM)", [("call", 1, atm)]),
        ("Long Put (ATM)", [("put", 1, atm)]),
        ("Bull Call Spread", [("call", 1, atm), ("call", -1, half_up)]),
        ("Bear Put Spread", [("put", 1, atm), ("put", -1, half_dn)]),
        ("Bull Put Spread (credit)", [("put", -1, atm), ("put", 1, half_dn)]),
        ("Bear Call Spread (credit)", [("call", -1, atm), ("call", 1, half_up)]),
        ("Long Straddle", [("call", 1, atm), ("put", 1, atm)]),
        ("Short Straddle", [("call", -1, atm), ("put", -1, atm)]),
        ("Short Strangle (1 SD)", [("call", -1, up), ("put", -1, dn)]),
        ("Iron Condor (1 SD)", [("call", -1, up), ("call", 1, chain.nearest_strike(up + wing)),
                                ("put", -1, dn), ("put", 1, chain.nearest_strike(dn - wing))]),
        ("Iron Butterfly", [("call", -1, atm), ("put", -1, atm),
                            ("call", 1, chain.nearest_strike(atm + em)),
                            ("put", 1, chain.nearest_strike(atm - em))]),
    ]
    out = []
    for name, legs in specs:
        built = [_leg(chain, k, s, st) for k, s, st in legs]
        if any(l.premium <= 0 for l in built):
            continue  # skip strategies with missing quotes
        # skip spreads that collapsed onto the same strike at the edge of the chain
        if len({(l.kind, l.strike) for l in built}) < len(built):
            continue
        out.append(Strategy(name, built, lot_size))
    return out
