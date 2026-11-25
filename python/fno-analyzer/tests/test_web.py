import json
import os
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

from fno_analyzer.web import Handler, api_analyze, api_futures, api_price, api_strategy

DATA = os.path.join(os.path.dirname(__file__), "..", "data", "sample_chain.csv")


class TestApi(unittest.TestCase):
    def test_analyze_sample(self):
        d = api_analyze({"source": "sample", "symbol": "NIFTY"})
        self.assertTrue(d["sample"])
        self.assertGreater(len(d["strategies"]), 5)
        json.dumps(d, allow_nan=False)  # must be strict-JSON serialisable
        for s in d["strategies"]:
            self.assertTrue(0 <= s["pop"] <= 1)
            self.assertGreater(len(s["curve"]), 50)

    def test_analyze_csv(self):
        with open(DATA) as f:
            d = api_analyze({"source": "csv", "csv": f.read(), "symbol": "NIFTY",
                             "spot": "24350", "expiry": "2026-12-01", "as_of": "2026-11-25"})
        self.assertEqual(d["atm"], 24350)

    def test_analyze_errors(self):
        with self.assertRaises(ValueError):
            api_analyze({"source": "csv", "csv": "", "spot": 1, "expiry": "2026-12-01"})
        with self.assertRaises(ValueError):
            api_analyze({"source": "nope"})

    def test_strategy(self):
        d = api_strategy({"spot": 24350, "iv": 12.5, "days": 6,
                          "legs": [{"side": -1, "kind": "call", "strike": 24800, "premium": 40},
                                   "SELL PE 23900 @ 45"]})
        self.assertTrue(d["unlimited_loss"])
        self.assertEqual(d["breakevens"], [23815.0, 24885.0])
        with self.assertRaises(ValueError):
            api_strategy({"spot": 24350, "iv": 12.5, "days": 6, "legs": []})

    def test_futures_and_price(self):
        f = api_futures({"spot": 24350, "future": 24460, "days": 20, "price_change": 10, "oi_change": 5})
        self.assertEqual(f["buildup"], "Long buildup")
        p = api_price({"spot": 24350, "strike": 24500, "days": 6, "type": "call", "premium": 105})
        self.assertAlmostEqual(p["price"], 105, places=2)


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_index(self):
        with urllib.request.urlopen(self.base + "/") as r:
            self.assertIn(b"F&amp;O Analyzer", r.read())

    def test_post_and_errors(self):
        req = urllib.request.Request(self.base + "/api/analyze", data=b'{"source":"sample"}',
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            self.assertEqual(json.load(r)["symbol"], "NIFTY")
        req = urllib.request.Request(self.base + "/api/strategy", data=b'{"spot":1}')
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 400)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(self.base + "/../web.py")
        self.assertEqual(cm.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
