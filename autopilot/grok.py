"""Grok's job: put the already-qualified candidates in order. Nothing else.

⚠️⚠️ THE MODEL CANNOT ADD A NAME, CHANGE A SIZE, OR MOVE A STOP. It receives a
list that `policy.qualify()` has already approved and returns a ranking; the
ranking is then intersected back with that same list, so a hallucinated ticker
is silently impossible rather than merely unlikely. Sizing and stops are
arithmetic and stay in policy.py.

The reason is not distrust of one vendor's model. It is that the reference
implementation of this system lost £424 running LLM-driven trading flows, and
the deterministic rebuild that replaced them is the reason there is anything
here worth automating. A model reordering four pre-screened names cannot repeat
that; a model choosing what to buy can.

⚠️ Grok is OPTIONAL. With no key the picks keep their incoming order, and every
safety property of this tool is identical.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from .config import Config
from .picks import Pick

_URL = "https://api.x.ai/v1/chat/completions"

_SYSTEM = (
    "You rank stock candidates that have ALREADY passed a mechanical filter. "
    "You are not deciding whether to buy them, how much to buy, or where the "
    "stop goes - those are fixed. Order them from most to least attractive on "
    "the evidence given, and reply with ONLY a JSON array of the tickers in "
    "your preferred order. No prose, no new tickers, no omissions."
)


def rank(picks: list[Pick], cfg: Config, log=print) -> list[Pick]:
    if not picks or not cfg.grok_key:
        return picks
    rows = [{"ticker": p.ticker, "symbol": p.symbol, "hit_rate": p.hit_rate,
             "stop_distance_pct": round(p.risk_pct * 100, 2),
             "reward_to_risk": (round((p.target - p.entry) / (p.entry - p.stop), 2)
                               if p.target and p.entry > p.stop else None),
             "note": p.note} for p in picks]
    body = json.dumps({
        "model": cfg.grok_model,
        "messages": [{"role": "system", "content": _SYSTEM},
                     {"role": "user", "content": json.dumps(rows)}],
        "temperature": 0.2,
    }).encode()
    req = urllib.request.Request(
        _URL, data=body,
        headers={"Authorization": f"Bearer {cfg.grok_key}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            content = (json.load(r)["choices"][0]["message"]["content"] or "").strip()
    except (urllib.error.URLError, KeyError, IndexError, ValueError) as e:
        # ⚠️ A dead model must not stop the run. The incoming order is a
        # perfectly good order; ranking is an improvement, not a dependency.
        log(f"  grok unavailable ({type(e).__name__}) - keeping the given order")
        return picks

    content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    try:
        order = json.loads(content)
    except ValueError:
        log("  grok did not return JSON - keeping the given order")
        return picks
    if not isinstance(order, list):
        return picks

    # ⚠️ INTERSECTED, NOT TRUSTED. Anything the model invented is dropped here;
    # anything it forgot is appended in its original position. The output set is
    # always exactly the input set.
    by_ticker = {p.ticker: p for p in picks}
    ranked = [by_ticker[t] for t in order
              if isinstance(t, str) and t in by_ticker]
    seen = {p.ticker for p in ranked}
    ranked += [p for p in picks if p.ticker not in seen]
    dropped = [t for t in order if isinstance(t, str) and t not in by_ticker]
    if dropped:
        log(f"  grok named {len(dropped)} ticker(s) that were not on the list "
            f"- ignored: {', '.join(map(str, dropped[:4]))}")
    return ranked
