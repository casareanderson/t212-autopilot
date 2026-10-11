#!/usr/bin/env python3
"""A stand-in for the Trading 212 demo API, for the setup check only. It answers the
four reads the CLI makes and records every order instead of placing it, so the check
can prove `plan` sends nothing, demo `apply` sends orders, and live mode refuses.
It holds one ETF so the safe sleeve has a price (the real API has no quote endpoint).

    python3 scripts/fake_t212.py 18110        # GET /_orders lists what was "placed"
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

ORDERS = []
READS = {
    "/api/v0/equity/account/info": {"id": 12345678, "currencyCode": "GBP"},
    "/api/v0/equity/account/cash": {"free": 100.0, "invested": 20.0, "total": 120.0},
    "/api/v0/equity/portfolio": [{"ticker": "VUAG_EQ", "quantity": 0.2, "currentPrice": 100.0}],
}


class H(BaseHTTPRequestHandler):
    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self):
        return self.headers.get("Authorization", "").startswith("Basic ")

    def do_GET(self):
        if self.path == "/_orders":
            return self._send(ORDERS)
        if not self._authed():
            return self._send({"code": "Unauthorized"}, 401)
        if self.path in READS:
            return self._send(READS[self.path])
        return self._send({"code": "NotFound"}, 404)

    def do_POST(self):
        if not self._authed():
            return self._send({"code": "Unauthorized"}, 401)
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path == "/api/v0/equity/orders/market":
            ORDERS.append(body)
            return self._send({"id": len(ORDERS), "status": "NEW", **body})
        return self._send({"code": "NotFound"}, 404)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
