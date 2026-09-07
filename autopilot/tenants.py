"""Which customer is asking, and whose account that means.

⚠️⚠️ THE CUSTOMER'S BROKER KEY NEVER APPEARS IN A URL. Grok is given a server
address and a bearer token; the token is looked up here and resolved to a
Trading 212 credential that stays on this machine. A key in a query string is
written into every proxy log, every browser history and every error report
between here and xAI - which is exactly how the bundle this project replaced
leaked one seller's account to anyone who knew their phone number.

The store is a JSON file, deliberately boring:

    {"tok_live_abc123": {"name": "Ben",
                         "t212_key": "...", "t212_secret": "...",
                         "mode": "demo", "stake_gbp": 250,
                         "safe_share": 0.9}}

⚠️ Tokens are compared with `secrets.compare_digest`, not `==`, because a
plain comparison leaks the length of the shared prefix to anyone timing it.
"""
from __future__ import annotations

import json
import os
import secrets as _secrets
from dataclasses import dataclass

from .config import Config

STORE = os.environ.get("AUTOPILOT_TENANTS", "tenants.json")


@dataclass
class Tenant:
    token: str
    name: str
    cfg: Config


def _load() -> dict:
    try:
        with open(STORE, encoding="utf-8") as fh:
            return json.load(fh) or {}
    except (OSError, ValueError):
        return {}


def resolve(bearer: str) -> Tenant | None:
    """The tenant this token belongs to, or None. Constant-time comparison."""
    if not bearer:
        return None
    for token, row in _load().items():
        if not _secrets.compare_digest(bearer, token):
            continue
        cfg = Config()
        cfg.key = str(row.get("t212_key") or "")
        cfg.secret = str(row.get("t212_secret") or "")
        # ⚠️ A tenant may only ever be MORE cautious than the server default.
        # `mode` is read from their row, but "live" here does not enable live
        # ORDERS - see mcp.py: there is no tool that places one.
        cfg.mode = str(row.get("mode") or "demo").lower()
        if row.get("stake_gbp"):
            cfg.stake_gbp = float(row["stake_gbp"])
        if row.get("safe_share") is not None:
            cfg.safe_share = float(row["safe_share"])
        if row.get("safe_tickers"):
            cfg.safe_tickers = list(row["safe_tickers"])
        if row.get("min_hit_rate") is not None:
            cfg.min_hit_rate = float(row["min_hit_rate"])
        return Tenant(token=token, name=str(row.get("name") or "?"), cfg=cfg)
    return None


def new_token(prefix: str = "tok") -> str:
    return f"{prefix}_{_secrets.token_urlsafe(24)}"
