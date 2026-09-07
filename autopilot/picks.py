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

import ipaddress
import json
import socket
import urllib.parse
import urllib.request
from dataclasses import dataclass


class UnsafeSource(ValueError):
    """The feed location is not one this server may fetch."""


def _check_url(url: str) -> str:
    """Refuse anything that is not a public https URL.

    ⚠️⚠️ FOUND BY PEN-TESTING THIS FILE, NOT BY READING IT. Two holes, both
    reachable by any authenticated customer over MCP:

      1. ARBITRARY LOCAL FILE READ. `load()` treated anything without an http
         prefix as a PATH and called open() on it, so `picks_url` of
         "/etc/passwd" - or "tenants.json", which holds every customer's broker
         secret - was read, parsed and reported back through the error message.
      2. SSRF, WITH A WORKING PORT SCANNER. `http://192.168.x.x:8080/` returned
         JSONDecodeError (reachable, not JSON) while an unreachable host
         returned URLError. That difference maps an internal network from
         outside it, and a host that DOES return JSON was parsed and used.

    So: https only, and the resolved address must be public. Resolution happens
    HERE and the result is checked, because "the hostname looks fine" is not the
    same statement as "it points somewhere public".
    """
    u = urllib.parse.urlparse(url or "")
    if u.scheme != "https":
        raise UnsafeSource(
            f"picks feed must be an https URL (got {u.scheme or 'no scheme'!r}). "
            f"Local paths are only allowed on the command line.")
    if not u.hostname:
        raise UnsafeSource("picks feed URL has no host")
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise UnsafeSource(f"cannot resolve {u.hostname!r}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        # ⚠️ EVERY resolved address is checked, not the first. A hostname with
        # one public and one loopback record would otherwise pass.
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise UnsafeSource(
                f"{u.hostname} resolves to {ip}, which is not a public address. "
                f"This server will not fetch internal hosts.")
    return url


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


def load(source: str, *, allow_local: bool = False) -> list[Pick]:
    """Read the feed.

    ⚠️ `allow_local` DEFAULTS TO FALSE, and only the CLI passes True. A local
    path is a reasonable thing to type at a terminal on your own machine and an
    arbitrary-file-read primitive when it arrives over the network.
    """
    looks_remote = "://" in source or source.startswith("//")
    if looks_remote or not allow_local:
        with urllib.request.urlopen(_check_url(source), timeout=30) as r:
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
