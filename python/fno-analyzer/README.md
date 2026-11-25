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
- **Web dashboard** — all of the above in your browser, with interactive charts.

Pure Python 3.8+ standard library — **no installs needed**.

## Try it online

**https://jiveshkaushal.github.io/basic-projects/** — the dashboard running entirely in your
browser (the Python code runs via Pyodide/WebAssembly; first load downloads ~10 MB).
Sample data, CSV upload and saved-NSE-JSON upload all work there and nothing leaves your
device. Live NSE fetching needs the local version below, because browsers block direct
requests to nseindia.com.

The site is rebuilt and deployed automatically by `.github/workflows/pages.yml` whenever
`python/fno-analyzer/` changes on `main` (tests run first). To preview the static build
locally: `./build_site.sh && python3 -m http.server -d _site 8080`.

## Web dashboard

```bash
cd python/fno-analyzer
python3 -m fno_analyzer serve --open      # opens http://127.0.0.1:8000
```

The dashboard has five tabs:

- **Overview** — key numbers (spot, ATM IV, PCR, max pain, support/resistance, bias), an
  open-interest-by-strike chart (total or today's change) with spot and max pain marked,
  the volatility smile, the market read, and the expected range to expiry.
- **Strategies & POP** — the preset strategies ranked by probability of profit (sortable);
  click one to see its payoff chart with profit/loss zones, breakevens and the 1-SD range.
- **Strategy builder** — add your own legs, fill premiums from the chain, and calculate.
- **Option chain** — the full chain with ITM shading and the ATM strike highlighted.
- **Futures & pricer** — futures basis/carry/buildup and a single-option pricer.

Choose the data source at the top: sample data, live NSE, an uploaded CSV, or a saved NSE
JSON file. Light and dark themes are supported. The server only listens on your own
computer (127.0.0.1) and uses no external libraries or CDNs.

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
