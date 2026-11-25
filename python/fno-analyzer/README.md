# F&O Analyzer — Indian Markets

A command-line tool for analysing **futures & options on NSE/BSE** (NIFTY, BANKNIFTY,
FINNIFTY, MIDCPNIFTY, SENSEX and stocks). It reads an option chain and gives you:

- **Option chain insights** — PCR (OI, volume, OI change), max pain, OI-based support &
  resistance, fresh OI buildup, ATM IV, IV skew, straddle price and the expected 1-SD / 2-SD
  range to expiry, plus an overall bullish/bearish bias score with the reasons behind it.
- **Probability of profit (POP)** for 11 common strategies built automatically from the chain
  (long call/put, bull/bear spreads, credit spreads, straddles, strangle, iron condor,
  iron butterfly) — with max profit, max loss, breakevens, expected P&L and Greeks.
- **Custom strategy analysis** — enter any legs (`BUY CE 24400 @ 150`, `SELL 2x PE 23800 @ 60`,
  `BUY FUT 24100`) and get POP, breakevens, Greeks and a P&L-at-expiry chart.
- **Futures analysis** — basis, implied cost of carry vs fair value, and OI buildup
  (long buildup, short buildup, short covering, long unwinding).
- **Option pricer** — Black-Scholes price, Greeks, implied volatility and probability of
  expiring in the money.

Pure Python 3.8+ standard library — **no installs needed**.

## Quick start

```bash
cd python/fno-analyzer

# Demo on built-in synthetic data
python3 -m fno_analyzer analyze --sample

# Live NSE data (run on your own machine; NSE may block cloud servers/VPNs)
python3 -m fno_analyzer analyze --live --symbol NIFTY
python3 -m fno_analyzer analyze --live --symbol BANKNIFTY --expiry 30-Dec-2026 --details
```

### Other data sources

If the live fetch fails (NSE changes its site and blocks bots from time to time):

```bash
# 1) Saved NSE JSON: open https://www.nseindia.com/option-chain in your browser,
#    then save the response of the "option-chain" API request from DevTools → Network.
python3 -m fno_analyzer analyze --json nifty.json --symbol NIFTY

# 2) CSV from any broker/terminal (IV columns optional — back-solved from LTP if blank)
python3 -m fno_analyzer analyze --csv data/sample_chain.csv --symbol NIFTY \
    --spot 24350 --expiry 2026-12-01 --as-of 2026-11-25
```

CSV header (IV in percent):
```
strike,call_ltp,call_iv,call_oi,call_oi_change,call_volume,put_ltp,put_iv,put_oi,put_oi_change,put_volume
```

### Custom strategy

```bash
python3 -m fno_analyzer strategy --symbol NIFTY --spot 24350 --iv 12.5 --days 6 \
    --name "Short Strangle" --leg "SELL CE 24800 @ 40" --leg "SELL PE 23900 @ 45"
```

### Futures

```bash
python3 -m fno_analyzer futures --symbol NIFTY --spot 24350 --future 24460 --days 20 \
    --price-change 85 --oi-change 120000
```

### Single option

```bash
python3 -m fno_analyzer price --spot 24350 --strike 24500 --days 6 --type call --premium 105
```

Useful flags: `--lot-size N` (override), `--rate 0.06` (risk-free rate), `--iv 14`
(override volatility used for POP), `--width 10` (strikes shown around ATM).

## How the probabilities work

- The underlying at expiry is modelled as **lognormal** with volatility = ATM implied
  volatility and zero drift (no directional view).
- A strategy's expiry payoff is piecewise-linear, so **breakevens, max profit and max loss
  are computed exactly**. POP = probability the price lands in the profitable zones.
- **Expected P&L** integrates the payoff over the same distribution. Near zero means the
  trade is roughly fairly priced by the model; it is not a forecast.
- High POP ≠ good trade. A short strangle may win 75% of the time but lose many times its
  credit on a big move. Always read POP together with max loss and reward/risk.

## Limitations

- Lognormal / Black-Scholes underestimates tail risk (gaps, event days, budget, RBI policy,
  election results). IV changes after you enter the trade.
- POP is for holding to expiry; it ignores early exits, stop-losses, brokerage, STT,
  exchange charges, GST, stamp duty and slippage.
- Lot sizes in `fno_analyzer/config.py` are revised periodically by the exchanges — verify
  on nseindia.com and pass `--lot-size` if they differ.
- The live NSE fetch is unofficial and best-effort.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## Disclaimer

Educational project, **not investment advice**. SEBI studies have found that the large
majority of individual F&O traders lose money. Trade only with capital you can afford to
lose, and consult a SEBI-registered investment adviser before trading.
