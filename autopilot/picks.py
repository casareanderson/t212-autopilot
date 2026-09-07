"""Where the candidates come from: a JSON feed you publish.

This tool deliberately does NOT contain a scanner. The picks are produced
elsewhere - by whatever logic you already trust - and arrive here as a list.
That separation is the point: the thing that decides what to buy and the thing
that buys it should be replaceable independently, and a bug in one should not be
able to hide inside the other.

Feed format (a file path or an https URL), one object per candidate:

    [{"ticker": "AAPL_US_EQ",     # the BROKER's ticker, not the exchange symbol
      "symbol": "AAPL",
      "entry": 231.40,
      "stop": 219.83,             # required: no exit, no trade
      "target": 243.0,
      "hit_rate": 0.62,           # the strategy's own measured hit rate
      "note": "blue-purple 4H"}]
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass


@dataclass
class Pick:
    ticker: str
    symbol: str = ""
    entry: float = 0.0
    stop: float = 0.0
    target: float = 0.0
    hit_rate: float = 0.0
    note: str = ""

    @property
    def risk_pct(self) -> float:
        """How far the stop is below the entry, as a fraction."""
        if not (self.entry and self.stop) or self.stop >= self.entry:
            return 0.0
        return (self.entry - self.stop) / self.entry


def load(source: str) -> list[Pick]:
    if source.startswith(("http://", "https://")):
        with urllib.request.urlopen(source, timeout=30) as r:
            raw = json.load(r)
    else:
        with open(source, encoding="utf-8") as fh:
            raw = json.load(fh)
    if isinstance(raw, dict):
        raw = raw.get("picks") or []
    out = []
    for d in raw:
        if not isinstance(d, dict) or not d.get("ticker"):
            continue
        out.append(Pick(ticker=str(d["ticker"]),
                        symbol=str(d.get("symbol") or ""),
                        entry=float(d.get("entry") or 0),
                        stop=float(d.get("stop") or 0),
                        target=float(d.get("target") or 0),
                        hit_rate=float(d.get("hit_rate") or 0),
                        note=str(d.get("note") or "")))
    return out
