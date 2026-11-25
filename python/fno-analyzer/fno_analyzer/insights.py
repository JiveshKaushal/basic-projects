"""Turns chain analytics into plain-English observations and a sentiment score."""
import math
from dataclasses import dataclass, field
from typing import List

from .chain import OptionChain


@dataclass
class Insights:
    score: int                       # -ve bearish, +ve bullish
    bias: str
    points: List[str] = field(default_factory=list)


def generate(chain: OptionChain) -> Insights:
    pts, score = [], 0
    spot = chain.spot

    pcr = chain.pcr_oi()
    if not math.isnan(pcr):
        if pcr > 1.5:
            pts.append(f"PCR (OI) {pcr:.2f} is very high: heavy put writing is supportive, "
                       "but extreme readings often precede pullbacks (contrarian warning).")
            score += 1
        elif pcr >= 1.0:
            pts.append(f"PCR (OI) {pcr:.2f} > 1: put writers dominate — mildly bullish.")
            score += 1
        elif pcr >= 0.7:
            pts.append(f"PCR (OI) {pcr:.2f} is in the neutral 0.7–1.0 zone.")
        else:
            pts.append(f"PCR (OI) {pcr:.2f} < 0.7: call writers dominate — bearish, "
                       "though very low readings can signal oversold conditions.")
            score -= 1

    chg = chain.pcr_oi_change()
    if not math.isnan(chg):
        if chg > 1.2:
            pts.append(f"Today's OI change PCR is {chg:.2f}: fresh put writing outpaces calls — bullish tilt.")
            score += 1
        elif chg < 0.8:
            pts.append(f"Today's OI change PCR is {chg:.2f}: fresh call writing outpaces puts — bearish tilt.")
            score -= 1

    mp = chain.max_pain()
    diff = (mp - spot) / spot * 100
    pts.append(f"Max pain {mp:g} is {diff:+.2f}% from spot. Prices often drift toward max pain "
               "into expiry, especially in the last 1–2 sessions, but it is not a target.")
    if abs(diff) > 0.5:
        score += 1 if diff > 0 else -1

    sup, res = chain.support(), chain.resistance()
    pts.append(f"OI-based support {sup:g} (highest put OI) and resistance {res:g} (highest call OI). "
               f"Range width {res - sup:g} pts.")
    if res - spot < spot - sup:
        pts.append("Spot is closer to resistance than support — upside may be capped near term.")
    elif spot - sup < res - spot:
        pts.append("Spot is closer to support than resistance — downside may be cushioned near term.")

    iv = chain.atm_iv()
    em1, em2 = chain.expected_move(), chain.expected_move(2)
    pts.append(f"ATM IV {iv * 100:.1f}% implies a 1-SD expiry range of {spot - em1:,.0f}–{spot + em1:,.0f} "
               f"(~68% probability) and 2-SD {spot - em2:,.0f}–{spot + em2:,.0f} (~95%).")
    straddle = chain.straddle_price()
    if straddle > 0:
        pts.append(f"ATM straddle costs {straddle:.2f} ({straddle / spot * 100:.2f}% of spot): "
                   f"the market's priced-in move to expiry.")

    skew = chain.iv_skew()
    if skew is not None:
        if skew > 0.03:
            pts.append(f"Put skew is steep ({skew * 100:+.1f} vol pts): strong demand for downside protection.")
            score -= 1
        elif skew < -0.01:
            pts.append(f"Call skew ({skew * 100:+.1f} vol pts): unusual demand for upside — bullish speculation.")
            score += 1
        else:
            pts.append(f"IV skew is normal ({skew * 100:+.1f} vol pts).")

    if chain.days_to_expiry <= 2:
        pts.append("Expiry is within 2 days: theta decay and gamma risk are at their highest.")

    bias = ("Bullish" if score >= 2 else "Mildly bullish" if score == 1 else
            "Bearish" if score <= -2 else "Mildly bearish" if score == -1 else "Neutral / range-bound")
    return Insights(score, bias, pts)


def strategy_hint(ins: Insights, iv: float) -> str:
    vol = "high" if iv >= 0.20 else "low" if iv <= 0.11 else "moderate"
    if ins.score >= 2:
        base = "bull call spread (low IV) or bull put spread (high IV)"
    elif ins.score <= -2:
        base = "bear put spread (low IV) or bear call spread (high IV)"
    else:
        base = "iron condor / short strangle (high IV) or calendar-style trades"
    return (f"With a {ins.bias.lower()} read and {vol} IV ({iv * 100:.1f}%), traders typically "
            f"consider: {base}. Always size so the max loss is acceptable.")
