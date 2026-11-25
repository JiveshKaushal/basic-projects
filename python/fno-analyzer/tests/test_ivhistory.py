import unittest
from datetime import date, timedelta

from fno_analyzer import ivhistory as ivh
from fno_analyzer.api import api_ivhistory


def series(vals, start=date(2026, 1, 1)):
    return [(start + timedelta(days=i), v) for i, v in enumerate(vals)]


class TestStats(unittest.TestCase):
    def test_percentile_and_rank(self):
        s = series([10, 12, 14, 16, 18, 20, 15])  # last value is "today"
        st = ivh.iv_stats(s)
        # 15 is above 10, 12, 14 -> 3 of 6 prior days
        self.assertAlmostEqual(st["percentile"], 50.0)
        self.assertAlmostEqual(st["rank"], 50.0)
        self.assertEqual((st["low"], st["high"], st["days"]), (10, 20, 6))

    def test_explicit_current_and_extremes(self):
        s = series([10, 12, 14, 16, 18, 20])
        self.assertEqual(ivh.iv_stats(s, current=25, as_of=date(2026, 1, 7))["percentile"], 100.0)
        self.assertEqual(ivh.iv_stats(s, current=25, as_of=date(2026, 1, 7))["rank"], 100.0)
        self.assertEqual(ivh.iv_stats(s, current=5, as_of=date(2026, 1, 7))["rank"], 0.0)

    def test_lookback_window(self):
        s = series([50] * 100 + [10] * 40 + [11, 12])  # old spike outside a 30-day window
        st = ivh.iv_stats(s, lookback_days=30)
        self.assertEqual(st["high"], 12)

    def test_regimes(self):
        self.assertEqual(ivh.regime(90), "Very high")
        self.assertEqual(ivh.regime(50), "Normal")
        self.assertEqual(ivh.regime(5), "Very low")

    def test_needs_history(self):
        with self.assertRaises(ValueError):
            ivh.iv_stats([])
        with self.assertRaises(ValueError):
            ivh.iv_stats(series([12]))


class TestParsers(unittest.TestCase):
    def test_nse_vix_csv(self):
        text = ("Date ,Open ,High ,Low ,Close ,Prev. Close ,Change ,% Change \n"
                "24-NOV-2026,14.1,14.9,13.8,14.5,14.0,0.5,3.5\n"
                "25-NOV-2026,14.5,15.2,14.2,15.0,14.5,0.5,3.4\n"
                "25-NOV-2026,14.5,15.2,14.2,15.1,14.5,0.6,3.4\n"
                "bad-date,1,1,1,1,1,0,0\n")
        s = ivh.parse_csv(text)
        self.assertEqual(s, [(date(2026, 11, 24), 14.5), (date(2026, 11, 25), 15.1)])

    def test_generic_csv(self):
        s = ivh.parse_csv("date,atm_iv\n2026-11-20,12.5\n2026-11-21,13\n")
        self.assertEqual(len(s), 2)
        with self.assertRaises(ValueError):
            ivh.parse_csv("foo,bar\n1,2\n")

    def test_nse_json(self):
        payload = {"data": [{"EOD_TIMESTAMP": "21-Nov-2026", "EOD_CLOSE_INDEX_VAL": "13.2"},
                            {"EOD_TIMESTAMP": "20-NOV-2026", "EOD_CLOSE_INDEX_VAL": 12.9}]}
        s = ivh.parse_nse_json(payload)
        self.assertEqual(s[0], (date(2026, 11, 20), 12.9))
        with self.assertRaises(ValueError):
            ivh.parse_nse_json({"data": []})

    def test_sample_history(self):
        s = ivh.sample_history(12.5, date(2026, 11, 25))
        self.assertEqual(s[-1], (date(2026, 11, 25), 12.5))
        self.assertGreater(len(s), 250)
        st = ivh.iv_stats(s)
        self.assertTrue(0 < st["percentile"] < 100)


class TestApi(unittest.TestCase):
    def test_sources(self):
        st = api_ivhistory({"source": "sample", "current": 12.5, "as_of": "2026-11-25"})
        self.assertIn("synthetic", st["basis"])
        self.assertGreater(len(st["series"]), 200)
        st = api_ivhistory({"source": "series", "series": [["2026-11-20", 12], ["2026-11-21", 14], ["2026-11-24", 13]],
                            "current": 13.5, "as_of": "2026-11-25", "basis": "Recorded ATM IV — NIFTY"})
        self.assertAlmostEqual(st["percentile"], 200 / 3)
        self.assertEqual(st["basis"], "Recorded ATM IV — NIFTY")
        st = api_ivhistory({"source": "json", "json": {"data": [
            {"EOD_TIMESTAMP": "20-Nov-2026", "EOD_CLOSE_INDEX_VAL": 12},
            {"EOD_TIMESTAMP": "21-Nov-2026", "EOD_CLOSE_INDEX_VAL": 16},
            {"EOD_TIMESTAMP": "24-Nov-2026", "EOD_CLOSE_INDEX_VAL": 14}]}})
        self.assertEqual(st["current"], 14)
        with self.assertRaises(ValueError):
            api_ivhistory({"source": "csv"})


if __name__ == "__main__":
    unittest.main()
