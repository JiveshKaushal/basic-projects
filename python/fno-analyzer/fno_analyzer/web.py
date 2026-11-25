"""Local web dashboard: a small JSON API over the analyzer plus a static page.

    python3 -m fno_analyzer serve            # http://127.0.0.1:8000
    python3 -m fno_analyzer serve --port 8080 --open

Standard library only. Binds to localhost by default — it is a personal tool,
not something to expose on the internet.
"""
import json
import os
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import __version__
from .api import DISCLAIMER, ROUTES
from .config import DEFAULT_RISK_FREE_RATE, LOT_SIZES

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
MAX_BODY = 5 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    server_version = f"FnoAnalyzer/{__version__}"

    def log_message(self, fmt, *args):  # quieter console
        if getattr(self.server, "verbose", False):
            super().log_message(fmt, *args)

    def _send(self, code, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, allow_nan=False).encode(), "application/json; charset=utf-8")

    def _api(self, path, params):
        try:
            self._json(200, ROUTES[path](params))
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
            self._json(400, {"error": str(e)})
        except Exception as e:  # pragma: no cover
            traceback.print_exc()
            self._json(500, {"error": f"Internal error: {e}"})

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ROUTES:
            params = {k: v[-1] for k, v in parse_qs(url.query).items()}
            return self._api(url.path, params)
        if url.path == "/api/meta":
            return self._json(200, {"version": __version__, "lot_sizes": LOT_SIZES,
                                    "rate": DEFAULT_RISK_FREE_RATE, "disclaimer": DISCLAIMER})
        files = {"/": ("index.html", "text/html; charset=utf-8"),
                 "/index.html": ("index.html", "text/html; charset=utf-8")}
        if url.path not in files:
            return self._send(404, b"Not found", "text/plain")
        name, ctype = files[url.path]
        with open(os.path.join(STATIC_DIR, name), "rb") as fh:
            self._send(200, fh.read(), ctype)

    def do_POST(self):
        url = urlparse(self.path)
        if url.path not in ROUTES:
            return self._json(404, {"error": "Not found"})
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._json(413, {"error": "Upload too large (max 5 MB)"})
        try:
            params = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "Body must be JSON"})
        self._api(url.path, params)


def serve(host: str = "127.0.0.1", port: int = 8000, open_browser: bool = False, verbose: bool = False):
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.verbose = verbose
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{httpd.server_address[1]}/"
    print(f"F&O Analyzer dashboard running at {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
