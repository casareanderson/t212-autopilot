"""A remote MCP server, so a customer with no hardware can use this from Grok.

Grok (and Claude, Cursor, anything speaking MCP) is given a URL and a bearer
token; xAI manages the connection. The customer needs nothing installed.

⚠️⚠️⚠️ THERE IS NO TOOL THAT BUYS ON A LIVE ACCOUNT, AND THAT IS THE MOST
IMPORTANT LINE IN THIS FILE. Over a CLI, buying takes a human typing
`apply --yes-live`. Over MCP, a `place_order` tool means the model can buy
because a conversation drifted that way - on someone else's money, following a
signal measured at -0.187R over 213 picks. The system this came from lost £424
to LLM-driven trading flows. So the tools here are:

    positions / cash / plan   read-only. `plan` computes and returns; it writes
                              nothing, ever.
    apply_demo                places orders ON THE DEMO ACCOUNT ONLY, and
                              refuses if the tenant is configured live.

Live execution stays a human action outside the chat. If that is ever relaxed,
it must be a signed, one-time confirmation the customer types - never a tool
the model can reach on its own.

Transport: JSON-RPC 2.0 over HTTP POST, which is what MCP is underneath. Only
the standard library is used, so this adds no dependency to the project.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import picks as picks_mod, policy
from .t212 import Client, T212Error
from .tenants import Tenant, resolve

PROTOCOL = "2025-06-18"
SERVER = {"name": "t212-autopilot", "version": "0.1.0"}

TOOLS = [
    {"name": "cash",
     "description": "Free and invested cash on the connected Trading 212 account.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "positions",
     "description": "Open positions: ticker, quantity, average and current price.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "plan",
     "description": ("What the 90/10 policy would buy from the given picks feed. "
                     "Computes only - places nothing. Returns the orders, the "
                     "stake headroom, and the reason any candidate was skipped."),
     "inputSchema": {"type": "object",
                     "properties": {"picks_url": {
                         "type": "string",
                         "description": "https URL of the picks feed JSON"}},
                     "required": ["picks_url"]}},
    {"name": "apply_demo",
     "description": ("Place the planned orders ON THE DEMO ACCOUNT. Refuses if "
                     "this connection is configured for the live account. There "
                     "is deliberately no live equivalent."),
     "inputSchema": {"type": "object",
                     "properties": {"picks_url": {"type": "string"}},
                     "required": ["picks_url"]}},
]


def _plan_for(t: Tenant, picks_url: str) -> tuple[policy.Plan, list]:
    feed = picks_mod.load(picks_url)
    qualified, notes = policy.qualify(feed, t.cfg)
    with Client(t.cfg) as c:
        prices = {p.get("ticker"): float(p.get("currentPrice") or 0)
                  for p in c.portfolio() if p.get("ticker")}
        for p in qualified:
            prices.setdefault(p.ticker, p.entry)
        plan = policy.build(t.cfg, c.cash(), c.portfolio(), qualified, prices)
    plan.notes = notes + plan.notes
    return plan, qualified


def _call(t: Tenant, name: str, args: dict) -> str:
    if name == "cash":
        with Client(t.cfg) as c:
            return json.dumps(c.cash(), indent=2)
    if name == "positions":
        with Client(t.cfg) as c:
            return json.dumps(c.portfolio(), indent=2)
    if name in ("plan", "apply_demo"):
        url = (args or {}).get("picks_url") or ""
        if not url:
            return "picks_url is required"
        plan, _ = _plan_for(t, url)
        lines = [f"mode: {t.cfg.mode}", *(f"· {n}" for n in plan.notes)]
        for o in plan.orders:
            lines.append(f"{o.sleeve:<5} {o.ticker:<14} qty {o.quantity:.6f}  "
                         f"£{o.notional_gbp:.2f}  {o.why}")
        lines.append(f"TOTAL £{plan.total_gbp:.2f}")
        if name == "plan":
            lines.append("computed only - nothing was placed")
            return "\n".join(lines)
        # ---- apply_demo -------------------------------------------------
        if t.cfg.mode != "demo":
            return ("REFUSED: this connection is configured for the live "
                    "account, and there is no tool here that buys with real "
                    "money. Run the CLI with --yes-live if that is what you "
                    "want.\n\n" + "\n".join(lines))
        with Client(t.cfg) as c:
            for o in plan.orders:
                try:
                    res = c.market_buy(o.ticker, o.quantity)
                    lines.append(f"placed {o.ticker} -> {res.get('id')}")
                except T212Error as e:
                    lines.append(f"FAILED {o.ticker}: {e}")
        return "\n".join(lines)
    return f"unknown tool {name!r}"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):        # quiet; the caller has its own log
        pass

    def _send(self, obj: dict, code: int = 200) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        # A liveness probe, and the only unauthenticated path.
        if self.path.startswith("/health"):
            self._send({"ok": True, "server": SERVER})
        else:
            self._send({"error": "POST JSON-RPC to /"}, 404)

    def do_POST(self) -> None:
        try:
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, TypeError):
            return self._send({"jsonrpc": "2.0", "id": None,
                               "error": {"code": -32700, "message": "parse error"}}, 400)

        method, rid = req.get("method"), req.get("id")
        # ⚠️ `initialize` and `tools/list` are answered WITHOUT credentials so a
        # client can discover the server, but every tool CALL is authenticated.
        if method == "initialize":
            return self._send({"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": PROTOCOL,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER}})
        if method in ("notifications/initialized", "notifications/cancelled"):
            self.send_response(202); self.send_header("Content-Length", "0")
            self.end_headers(); return
        if method == "tools/list":
            return self._send({"jsonrpc": "2.0", "id": rid,
                               "result": {"tools": TOOLS}})
        if method != "tools/call":
            return self._send({"jsonrpc": "2.0", "id": rid,
                               "error": {"code": -32601,
                                         "message": f"unknown method {method!r}"}})

        auth = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        tenant = resolve(auth)
        if not tenant:
            # ⚠️ The same message whether the token is absent, malformed or
            # simply wrong. Distinguishing them is a free oracle for guessing.
            return self._send({"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text",
                             "text": "not authorised for this server"}],
                "isError": True}})

        params = req.get("params") or {}
        try:
            text = _call(tenant, params.get("name") or "",
                         params.get("arguments") or {})
            err = False
        except (T212Error, OSError, ValueError) as e:
            text, err = f"{type(e).__name__}: {e}", True
        self._send({"jsonrpc": "2.0", "id": rid,
                    "result": {"content": [{"type": "text", "text": text}],
                               "isError": err}})


def serve(host: str = "0.0.0.0", port: int = 8790) -> None:
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"t212-autopilot MCP on http://{host}:{port}  "
          f"({len(TOOLS)} tools, none of which buy on a live account)",
          flush=True)
    srv.serve_forever()
