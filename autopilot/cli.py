"""`python -m autopilot <command>` - check, plan, apply.

⚠️⚠️ `plan` NEVER WRITES AND `apply` ALWAYS PRINTS THE PLAN FIRST. Going live
additionally requires --yes-live, typed at the moment of the order, because an
environment variable set weeks ago is not consent.
"""
from __future__ import annotations

import argparse
import sys

from . import grok as grok_mod, picks as picks_mod, policy
from .config import Config
from .t212 import Client, T212Error


def _log(m: str = "") -> None:
    print(m, flush=True)


def _prices(client: Client, tickers: set[str]) -> dict[str, float]:
    """Last price per ticker, from the portfolio where held, else the pick's
    own entry. ⚠️ T212's public API has no quote endpoint on this plan, so a
    name that is neither held nor priced by the feed is skipped rather than
    guessed at."""
    out: dict[str, float] = {}
    for p in client.portfolio():
        t = p.get("ticker")
        px = float(p.get("currentPrice") or 0)
        if t in tickers and px > 0:
            out[t] = px
    return out


def main() -> None:
    ap = argparse.ArgumentParser(prog="autopilot")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="prove the credentials reach the right account")
    s = sub.add_parser("serve", help="run the remote MCP server (for Grok etc.)")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8790)
    sub.add_parser("new-token", help="mint a customer token for tenants.json")
    for name in ("plan", "apply"):
        p = sub.add_parser(name)
        p.add_argument("--picks", default="picks.json",
                       help="path or https URL of the picks feed")
        if name == "apply":
            p.add_argument("--yes-live", action="store_true",
                           help="required to place orders on the LIVE account")
    args = ap.parse_args()

    if args.cmd == "new-token":
        from .tenants import new_token
        print(new_token())
        return
    if args.cmd == "serve":
        # ⚠️ No Config() check here: the server has no credentials of its own.
        # Every tool call resolves the CUSTOMER's key from their bearer token.
        from .mcp import serve
        serve(args.host, args.port)
        return

    cfg = Config()
    problems = cfg.problems()
    if problems:
        for p in problems:
            _log(f"  ✗ {p}")
        sys.exit(1)

    banner = "LIVE - REAL MONEY" if cfg.mode == "live" else "demo"
    _log(f"mode: {banner}   stake ceiling: £{cfg.stake_gbp:.2f}   "
         f"split: {cfg.safe_share:.0%} safe / {cfg.risk_share:.0%} risk")

    try:
        with Client(cfg) as client:
            if args.cmd == "check":
                info = client.verify()
                cash = client.cash()
                _log(f"  account : {info.get('id')} ({info.get('currencyCode')})")
                if info.get("_warning"):
                    _log(f"  ⚠️ {info['_warning']}")
                _log(f"  free    : £{float(cash.get('free') or 0):.2f}")
                _log(f"  invested: £{float(cash.get('invested') or 0):.2f}")
                _log("  ok - credentials reach this account")
                return

            feed = picks_mod.load(args.picks)
            _log(f"  {len(feed)} candidate(s) in the feed")
            qualified, notes = policy.qualify(feed, cfg)
            for n in notes:
                _log(f"  · {n}")
            qualified = grok_mod.rank(qualified, cfg, log=_log)
            _log(f"  {len(qualified)} qualified after filtering")

            wanted = set(cfg.safe_tickers) | {p.ticker for p in qualified}
            prices = _prices(client, wanted)
            for p in qualified:
                prices.setdefault(p.ticker, p.entry)

            plan = policy.build(cfg, client.cash(), client.portfolio(),
                                qualified, prices)
            _log("")
            for n in plan.notes:
                _log(f"  · {n}")
            if not plan.orders:
                _log("  nothing to do")
                return
            _log("")
            _log("  sleeve  ticker            qty        £        why")
            for o in plan.orders:
                _log(f"  {o.sleeve:<6}  {o.ticker:<16} {o.quantity:<10.6f} "
                     f"{o.notional_gbp:>7.2f}  {o.why}")
            _log(f"  {'':<6}  {'TOTAL':<16} {'':<10} {plan.total_gbp:>7.2f}")

            if args.cmd == "plan":
                _log("\n  plan only - nothing was sent")
                return
            if cfg.mode == "live" and not args.yes_live:
                _log("\n  REFUSED: mode is live and --yes-live was not given")
                sys.exit(2)

            _log("")
            for o in plan.orders:
                try:
                    res = client.market_buy(o.ticker, o.quantity)
                    _log(f"  placed {o.ticker} x{o.quantity} -> {res.get('id')}")
                except T212Error as e:
                    # ⚠️ Reported and moved past. One rejected order must not
                    # abandon the rest of a plan that was already approved.
                    _log(f"  FAILED {o.ticker}: {e}")
    except T212Error as e:
        _log(f"  ✗ {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
