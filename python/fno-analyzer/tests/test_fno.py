import math
import os
import unittest
from datetime import date

from fno_analyzer.chain import from_csv, from_nse_json
from fno_analyzer.futures import analyze_basis, classify_buildup
from fno_analyzer.insights import generate
from fno_analyzer.presets import build_presets
from fno_analyzer.pricing import bs_price, greeks, implied_vol, prob_itm
from fno_analyzer.sample import sample_chain
from fno_analyzer.strategy import Leg, Strategy, analyze, lognormal_cdf, parse_leg, probability_of_profit

DATA = os.path.join(os.path.dirname(__file__), "..", "data", "sample_chain.csv")


class TestPricing(unittest.TestCase):
    def test_known_value(self):
        # Hull example: S=42, K=40, r=10%, sigma=20%, T=0.5 -> call 4.76, put 0.81
        self.assertAlmostEqual(bs_price(42, 40, 0.5, 0.1, 0.2, "call"), 4.76, places=2)
        self.assertAlmostEqual(bs_price(42, 40, 0.5, 0.1, 0.2, "put"), 0.81, places=2)

    def test_put_call_parity(self):
        S, K, T, r, v = 24350, 24500, 10 / 365, 0.055, 0.13
        c, p = bs_price(S, K, T, r, v, "call"), bs_price(S, K, T, r, v, "put")
        self.assertAlmostEqual(c - p, S - K * math.exp(-r * T), places=6)

    def test_implied_vol_roundtrip(self):
        price = bs_price(24350, 24500, 6 / 365, 0.055, 0.137, "call")
        self.assertAlmostEqual(implied_vol(price, 24350, 24500, 6 / 365, 0.055, "call"), 0.137, places=4)

    def test_greeks_signs(self):
        gc = greeks(24350, 24350, 7 / 365, 0.055, 0.13, "call")
        gp = greeks(24350, 24350, 7 / 365, 0.055, 0.13, "put")
        self.assertTrue(0 < gc["delta"] < 1 and -1 < gp["delta"] < 0)
        self.assertAlmostEqual(gc["delta"] - gp["delta"], 1.0, places=6)
        self.assertLess(gc["theta"], 0)
        self.assertGreater(gc["vega"], 0)

    def test_prob_itm_bounds(self):
        p = prob_itm(100, 100, 0.1, 0, 0.2, "call") + prob_itm(100, 100, 0.1, 0, 0.2, "put")
        self.assertAlmostEqual(p, 1.0, places=9)


class TestStrategy(unittest.TestCase):
    def test_long_call(self):
        s = Strategy("LC", [Leg("call", 1, 100, 5)], 1)
        self.assertEqual(s.breakevens(100), [105])
        mp, ml = s.max_profit_loss(100)
        self.assertEqual(mp, math.inf)
        self.assertEqual(ml, -5)
        pop = probability_of_profit(s, 100, 0.2, 0.1)
        self.assertAlmostEqual(pop, 1 - lognormal_cdf(105, 100, 0.2, 0.1), places=9)

    def test_iron_condor(self):
        legs = [Leg("put", 1, 90, 1), Leg("put", -1, 95, 2), Leg("call", -1, 105, 2), Leg("call", 1, 110, 1)]
        s = Strategy("IC", legs, 10)
        self.assertEqual(s.breakevens(100), [93, 107])
        mp, ml = s.max_profit_loss(100)
        self.assertAlmostEqual(mp, 20)
        self.assertAlmostEqual(ml, -30)
        rep = analyze(s, 100, 0.2, 30 / 365)
        expected = lognormal_cdf(107, 100, 0.2, 30 / 365) - lognormal_cdf(93, 100, 0.2, 30 / 365)
        self.assertAlmostEqual(rep.pop, expected, places=9)

    def test_short_put_unlimited_flags(self):
        s = Strategy("SP", [Leg("put", -1, 100, 3)], 1)
        mp, ml = s.max_profit_loss(100)
        self.assertEqual(mp, 3)
        self.assertEqual(ml, -97)  # put loss is bounded at S=0

    def test_risk_neutral_fair_trade_has_zero_ev(self):
        S, K, T, r, v = 100, 100, 0.25, 0.0, 0.2
        prem = bs_price(S, K, T, r, v, "call")
        rep = analyze(Strategy("LC", [Leg("call", 1, K, prem)], 1), S, v, T, r, mu=r)
        self.assertAlmostEqual(rep.expected_pnl, 0.0, places=3)

    def test_parse_leg(self):
        l = parse_leg("sell 2x PE 23500 @ 60.5")
        self.assertEqual((l.kind, l.side, l.strike, l.premium, l.lots), ("put", -1, 23500, 60.5, 2))
        self.assertEqual(parse_leg("BUY FUT 24100").kind, "future")
        with self.assertRaises(ValueError):
            parse_leg("BUY CE 24000")


class TestChain(unittest.TestCase):
    def setUp(self):
        self.chain = sample_chain("NIFTY", days=6, as_of=date(2026, 11, 25))

    def test_basic_metrics(self):
        c = self.chain
        self.assertEqual(c.strike_step, 50)
        self.assertEqual(c.atm_strike(), 24350)
        self.assertGreater(c.pcr_oi(), 0)
        self.assertIn(c.max_pain(), c.strikes)
        self.assertLess(c.support(), c.spot)
        self.assertGreater(c.resistance(), c.spot)
        self.assertAlmostEqual(c.atm_iv(), 0.125, places=3)

    def test_max_pain_simple(self):
        from fno_analyzer.chain import OptionChain, Quote, StrikeRow
        rows = [StrikeRow(k, Quote(1, 0.1, coi), Quote(1, 0.1, poi))
                for k, coi, poi in [(90, 0, 100), (100, 50, 50), (110, 100, 0)]]
        c = OptionChain("X", 100, date(2026, 12, 1), rows, as_of=date(2026, 11, 25))
        self.assertEqual(c.max_pain(), 100)

    def test_csv_loader(self):
        c = from_csv(DATA, "NIFTY", 24350, "2026-12-01", as_of="2026-11-25")
        self.assertEqual(len(c.rows), 61)
        self.assertAlmostEqual(c.atm_iv(), 0.125, places=3)

    def test_csv_backsolves_missing_iv(self):
        import csv, tempfile
        with open(DATA) as f:
            rows = list(csv.DictReader(f))
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="") as f:
            w = csv.DictWriter(f, fieldnames=rows[0].keys())
            w.writeheader()
            for r in rows:
                r["call_iv"] = r["put_iv"] = ""
                w.writerow(r)
        c = from_csv(f.name, "NIFTY", 24350, "2026-12-01", as_of="2026-11-25")
        os.unlink(f.name)
        self.assertAlmostEqual(c.atm_iv(), 0.125, delta=0.002)

    def test_nse_json(self):
        payload = {"records": {
            "expiryDates": ["01-Dec-2026", "08-Dec-2026"], "underlyingValue": 24350.0,
            "timestamp": "25-Nov-2026 15:30:00",
            "data": [
                {"strikePrice": 24300, "expiryDate": "01-Dec-2026",
                 "CE": {"lastPrice": 200, "impliedVolatility": 12.6, "openInterest": 1000,
                        "changeinOpenInterest": 100, "totalTradedVolume": 5000},
                 "PE": {"lastPrice": 128, "impliedVolatility": 12.6, "openInterest": 1500,
                        "changeinOpenInterest": 200, "totalTradedVolume": 6000}},
                {"strikePrice": 24400, "expiryDate": "01-Dec-2026",
                 "CE": {"lastPrice": 148, "impliedVolatility": 12.4, "openInterest": 2000},
                 "PE": {"lastPrice": 175, "impliedVolatility": 12.4, "openInterest": 900}},
                {"strikePrice": 24400, "expiryDate": "08-Dec-2026",
                 "CE": {"lastPrice": 250}, "PE": {"lastPrice": 280}},
            ]}}
        c = from_nse_json(payload, "nifty")
        self.assertEqual(len(c.rows), 2)
        self.assertEqual(c.expiry, date(2026, 12, 1))
        self.assertEqual(c.as_of, date(2026, 11, 25))
        self.assertAlmostEqual(c.pcr_oi(), 2400 / 3000)

    def test_presets_and_insights(self):
        strategies = build_presets(self.chain, 65)
        self.assertGreaterEqual(len(strategies), 8)
        for s in strategies:
            rep = analyze(s, self.chain.spot, self.chain.atm_iv(), self.chain.T)
            self.assertTrue(0 <= rep.pop <= 1, s.name)
        ins = generate(self.chain)
        self.assertTrue(ins.points)


class TestFutures(unittest.TestCase):
    def test_basis(self):
        v = analyze_basis(24000, 24100, 30, 0.055)
        self.assertAlmostEqual(v.basis, 100)
        self.assertGreater(v.implied_carry, 0.05)

    def test_buildup(self):
        self.assertEqual(classify_buildup(10, 100)[0], "Long buildup")
        self.assertEqual(classify_buildup(-10, 100)[0], "Short buildup")
        self.assertEqual(classify_buildup(10, -100)[0], "Short covering")
        self.assertEqual(classify_buildup(-10, -100)[0], "Long unwinding")


class TestCLI(unittest.TestCase):
    def test_commands_run(self):
        import io
        from contextlib import redirect_stdout
        from fno_analyzer.cli import main
        for argv in (["analyze", "--sample", "--details"],
                     ["analyze", "--csv", DATA, "--spot", "24350", "--expiry", "2026-12-01", "--as-of", "2026-11-25"],
                     ["strategy", "--spot", "24350", "--iv", "13", "--days", "6", "--leg", "BUY CE 24400 @ 150"],
                     ["futures", "--spot", "24350", "--future", "24420", "--days", "20"],
                     ["price", "--spot", "24350", "--strike", "24500", "--days", "6", "--type", "put", "--iv", "13"]):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(argv), 0, argv)


if __name__ == "__main__":
    unittest.main()
