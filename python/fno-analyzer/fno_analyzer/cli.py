"""Command-line interface.

  python -m fno_analyzer analyze --sample
  python -m fno_analyzer analyze --live --symbol NIFTY
  python -m fno_analyzer strategy --spot 24350 --iv 13 --days 6 --leg "SELL CE 24800 @ 40" --leg "SELL PE 23900 @ 45"
  python -m fno_analyzer futures --spot 24350 --future 24420 --days 20
  python -m fno_analyzer price --spot 24350 --strike 24500 --days 6 --iv 13 --type call
"""
import argparse
import math
import sys

from . import __version__
from .chain import fetch_nse, from_csv, from_json_file
from .config import DEFAULT_RISK_FREE_RATE, DAYS_IN_YEAR, lot_size
from .futures import analyze_basis, classify_buildup
from .insights import generate, strategy_hint
from .presets import build_presets
from .pricing import bs_price, greeks, implied_vol, prob_itm
from .sample import sample_chain
from .strategy import Strategy, analyze, parse_leg

DISCLAIMER = ("Educational tool only — not investment advice. Probabilities come from a lognormal "
              "model using implied volatility; real markets have fat tails, gaps and changing IV. "
              "SEBI studies show most individual F&O traders lose money. Trade only with risk "
              "capital and consult a SEBI-registered adviser.")


def rupees(x: float) -> str:
    if x == math.inf:
        return "Unlimited"
    if x == -math.inf:
        return "-Unlimited"
    return f"-₹{-x:,.0f}" if x < 0 else f"₹{x:,.0f}"


def hr(title: str = ""):
    print()
    print(f"── {title} " + "─" * max(0, 70 - len(title)) if title else "─" * 74)


def print_report(rep, show_legs=True):
    s = rep.strategy
    if show_legs:
        for l in s.legs:
            print(f"    {l.describe()}")
    print(f"  Net premium : {rupees(rep.net_premium)} ({'credit' if rep.net_premium > 0 else 'debit'})")
    print(f"  Max profit  : {rupees(rep.max_profit)}")
    print(f"  Max loss    : {rupees(rep.max_loss)}")
    print(f"  Breakevens  : {', '.join(f'{b:,.2f}' for b in rep.breakevens) or 'none'}")
    print(f"  POP         : {rep.pop * 100:.1f}%")
    print(f"  Expected P&L: {rupees(rep.expected_pnl)} (model)")
    if rep.reward_risk is not None:
        print(f"  Reward/risk : {rep.reward_risk:.2f}")
    g = rep.greeks
    print(f"  Greeks      : Δ {g['delta']:+.1f}  Γ {g['gamma']:+.4f}  "
          f"Θ {rupees(g['theta'])}/day  Vega {rupees(g['vega'])}/vol-pt")


def load_chain(args):
    if args.sample:
        return sample_chain(args.symbol, days=args.days or 6)
    if args.csv:
        if not (args.spot and args.expiry):
            sys.exit("--csv requires --spot and --expiry")
        return from_csv(args.csv, args.symbol, args.spot, args.expiry, args.as_of, args.rate)
    if args.json:
        return from_json_file(args.json, args.symbol, args.expiry, args.rate)
    if args.live:
        return fetch_nse(args.symbol, args.expiry, rate=args.rate)
    sys.exit("Choose a data source: --live, --csv FILE, --json FILE or --sample")


def cmd_analyze(args):
    chain = load_chain(args)
    lots = args.lot_size or lot_size(chain.symbol)
    iv = args.iv / 100 if args.iv else chain.atm_iv()
    if iv <= 0:
        sys.exit("Could not determine ATM IV; pass --iv")

    hr(f"{chain.symbol} option chain")
    if args.sample:
        print("  ⚠ SAMPLE DATA — synthetic numbers for demonstration, not live prices.")
    print(f"  Spot {chain.spot:,.2f} | Expiry {chain.expiry} ({chain.days_to_expiry - 0.5:.0f} days) | "
          f"Lot {lots} | ATM {chain.atm_strike():g}")
    c_oi, p_oi = chain.total_oi()
    print(f"  ATM IV {iv * 100:.2f}% | PCR OI {chain.pcr_oi():.2f} | PCR Vol {chain.pcr_volume():.2f} | "
          f"Max pain {chain.max_pain():g}")
    print(f"  Total call OI {c_oi:,.0f} | Total put OI {p_oi:,.0f}")
    print("  Top call OI (resistance): " + ", ".join(f"{k:g} ({v:,.0f})" for k, v in chain.top_oi("call")))
    print("  Top put OI  (support)   : " + ", ".join(f"{k:g} ({v:,.0f})" for k, v in chain.top_oi("put")))
    print("  Top call OI added       : " + ", ".join(f"{k:g} ({v:+,.0f})" for k, v in chain.top_oi("call", key="oi_change")))
    print("  Top put OI added        : " + ", ".join(f"{k:g} ({v:+,.0f})" for k, v in chain.top_oi("put", key="oi_change")))

    hr("Chain around ATM")
    print(f"  {'Call OI':>11} {'Chg':>9} {'IV%':>6} {'LTP':>9} │ {'Strike':^8} │ "
          f"{'LTP':>9} {'IV%':>6} {'Chg':>9} {'Put OI':>11}")
    atm = chain.atm_strike()
    for r in chain.rows:
        if abs(r.strike - atm) <= chain.strike_step * args.width:
            mark = "*" if r.strike == atm else " "
            print(f"  {r.call.oi:>11,.0f} {r.call.oi_change:>+9,.0f} {r.call.iv * 100:>6.1f} {r.call.ltp:>9.2f} │"
                  f"{mark}{r.strike:^8g}{mark}│ {r.put.ltp:>9.2f} {r.put.iv * 100:>6.1f} "
                  f"{r.put.oi_change:>+9,.0f} {r.put.oi:>11,.0f}")

    ins = generate(chain)
    hr(f"Insights — overall bias: {ins.bias} (score {ins.score:+d})")
    for p in ins.points:
        print(f"  • {p}")
    print(f"  • {strategy_hint(ins, iv)}")

    hr("Strategy probabilities (1 lot each, held to expiry)")
    reports = [analyze(s, chain.spot, iv, chain.T, chain.rate) for s in build_presets(chain, lots)]
    reports.sort(key=lambda r: r.pop, reverse=True)
    print(f"  {'Strategy':<26} {'POP':>6} {'Max profit':>12} {'Max loss':>12} {'Exp. P&L':>10}  Breakevens")
    for rep in reports:
        print(f"  {rep.strategy.name:<26} {rep.pop * 100:>5.1f}% {rupees(rep.max_profit):>12} "
              f"{rupees(rep.max_loss):>12} {rupees(rep.expected_pnl):>10}  "
              + ", ".join(f"{b:,.0f}" for b in rep.breakevens))
    print("\n  Note: high-POP strategies win often but small, and lose big when they lose.\n"
          "  Compare POP together with max loss and reward/risk — not POP alone.")
    if args.details:
        for rep in reports:
            hr(rep.strategy.name)
            print_report(rep)

    hr()
    print("  " + DISCLAIMER)


def cmd_strategy(args):
    legs = [parse_leg(l) for l in args.leg]
    T = (args.days + 0.5) / DAYS_IN_YEAR
    iv = args.iv / 100
    for l in legs:
        l.iv = iv
    lots = args.lot_size or lot_size(args.symbol)
    strat = Strategy(args.name, legs, lots)
    rep = analyze(strat, args.spot, iv, T, args.rate)
    hr(f"{args.name} — {args.symbol.upper()} (lot {lots})")
    print_report(rep)
    hr("P&L at expiry")
    em = args.spot * iv * math.sqrt(T)
    rows = [(k, args.spot + k * em / 2) for k in range(-4, 5)]
    pnls = [strat.payoff(S) for _, S in rows]
    scale = max(abs(p) for p in pnls) or 1
    for (k, S), pnl in zip(rows, pnls):
        bar = "█" * round(abs(pnl) / scale * 30)
        left, right = (bar.rjust(30), "") if pnl < 0 else ("".rjust(30), bar)
        print(f"  {S:>10,.0f} ({k * 0.5:+.1f} SD)  {rupees(pnl):>10}  {left}│{right}")
    hr()
    print("  " + DISCLAIMER)


def cmd_futures(args):
    v = analyze_basis(args.spot, args.future, args.days, args.rate, args.div / 100)
    hr("Futures analysis")
    print(f"  Basis          : {v.basis:+,.2f} ({v.basis_pct:+.2f}%) — "
          f"{'premium (contango)' if v.basis > 0 else 'discount (backwardation)'}")
    print(f"  Implied carry  : {v.implied_carry * 100:.2f}% p.a. (vs rate {args.rate * 100:.2f}%)")
    print(f"  Fair value     : {v.fair_value:,.2f} → future is {v.premium_to_fair:+,.2f} vs fair")
    if v.implied_carry > args.rate + 0.02:
        print("  Read           : Rich premium — aggressive long positioning / bullish sentiment.")
    elif v.implied_carry < args.rate - 0.02:
        print("  Read           : Thin/negative carry — short positioning or dividend effect; bearish tilt.")
    else:
        print("  Read           : Carry is near the risk-free rate — neutral.")
    if args.price_change is not None and args.oi_change is not None:
        name, desc = classify_buildup(args.price_change, args.oi_change)
        print(f"  OI buildup     : {name} — {desc}")
    lots = args.lot_size or lot_size(args.symbol)
    print(f"  1 lot ({lots}) notional: {rupees(args.future * lots)}; "
          f"each 1% move = {rupees(args.future * lots / 100)}")
    hr()
    print("  " + DISCLAIMER)


def cmd_price(args):
    T = (args.days + 0.5) / DAYS_IN_YEAR
    if args.premium and not args.iv:
        iv = implied_vol(args.premium, args.spot, args.strike, T, args.rate, args.type)
        if iv is None:
            sys.exit("No implied volatility matches that premium.")
    elif args.iv:
        iv = args.iv / 100
    else:
        sys.exit("Pass --iv or --premium")
    price = bs_price(args.spot, args.strike, T, args.rate, iv, args.type)
    g = greeks(args.spot, args.strike, T, args.rate, iv, args.type)
    hr(f"{args.type.upper()} {args.strike:g}")
    print(f"  IV {iv * 100:.2f}% | Theoretical price {price:.2f}"
          + (f" | Market {args.premium:.2f}" if args.premium else ""))
    print(f"  Delta {g['delta']:+.3f} | Gamma {g['gamma']:.5f} | Theta {g['theta']:+.2f}/day | "
          f"Vega {g['vega']:.2f}/vol-pt | Rho {g['rho']:+.2f}")
    print(f"  Probability of expiring ITM: {prob_itm(args.spot, args.strike, T, args.rate, iv, args.type) * 100:.1f}%")


def build_parser():
    p = argparse.ArgumentParser(prog="fno_analyzer", description="Indian F&O analysis tool")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--symbol", default="NIFTY")
        sp.add_argument("--rate", type=float, default=DEFAULT_RISK_FREE_RATE, help="risk-free rate (decimal)")
        sp.add_argument("--lot-size", type=int, help="override lot size")

    a = sub.add_parser("analyze", help="analyse an option chain")
    common(a)
    src = a.add_mutually_exclusive_group()
    src.add_argument("--live", action="store_true", help="fetch from nseindia.com (best effort)")
    src.add_argument("--csv", help="option chain CSV file")
    src.add_argument("--json", help="saved NSE option-chain JSON file")
    src.add_argument("--sample", action="store_true", help="use built-in synthetic data")
    a.add_argument("--spot", type=float)
    a.add_argument("--expiry", help="expiry date (YYYY-MM-DD or DD-Mon-YYYY)")
    a.add_argument("--as-of", help="valuation date for CSV data (default today)")
    a.add_argument("--days", type=int, help="days to expiry for --sample")
    a.add_argument("--iv", type=float, help="override volatility in %% for POP")
    a.add_argument("--width", type=int, default=6, help="strikes shown each side of ATM")
    a.add_argument("--details", action="store_true", help="print each strategy's legs and Greeks")
    a.set_defaults(func=cmd_analyze)

    s = sub.add_parser("strategy", help="analyse a custom strategy")
    common(s)
    s.add_argument("--spot", type=float, required=True)
    s.add_argument("--iv", type=float, required=True, help="volatility in %%, e.g. 13.5")
    s.add_argument("--days", type=float, required=True, help="calendar days to expiry")
    s.add_argument("--leg", action="append", required=True,
                   help="e.g. 'BUY CE 24000 @ 120', 'SELL 2x PE 23500 @ 60', 'BUY FUT 24100'")
    s.add_argument("--name", default="Custom strategy")
    s.set_defaults(func=cmd_strategy)

    f = sub.add_parser("futures", help="futures basis & buildup")
    common(f)
    f.add_argument("--spot", type=float, required=True)
    f.add_argument("--future", type=float, required=True)
    f.add_argument("--days", type=float, required=True)
    f.add_argument("--div", type=float, default=1.2, help="dividend yield %% (default 1.2)")
    f.add_argument("--price-change", type=float, help="today's futures price change")
    f.add_argument("--oi-change", type=float, help="today's futures OI change")
    f.set_defaults(func=cmd_futures)

    pr = sub.add_parser("price", help="price an option / Greeks / implied vol")
    pr.add_argument("--spot", type=float, required=True)
    pr.add_argument("--strike", type=float, required=True)
    pr.add_argument("--days", type=float, required=True)
    pr.add_argument("--type", choices=["call", "put"], required=True)
    pr.add_argument("--iv", type=float, help="volatility in %%")
    pr.add_argument("--premium", type=float, help="market premium (solves IV)")
    pr.add_argument("--rate", type=float, default=DEFAULT_RISK_FREE_RATE)
    pr.set_defaults(func=cmd_price)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except (ValueError, RuntimeError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0
