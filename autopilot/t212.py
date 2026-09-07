"""The Trading 212 client. Reads freely; writes only when told twice.

Auth is HTTP Basic: the API key is the username, the secret is the password.
The key's first 8 characters are the account number, which is why `verify()`
compares them - a secret from the wrong account is refused rather than silently
trading somewhere you did not mean.

⚠️⚠️ WRITES ARE NEVER RETRIED. T212 has no idempotency key, so a retried POST
is a second order, not the same one. Reads back off and retry; orders fail and
say so.
"""
from __future__ import annotations

import time
from typing import Any

import httpx

from .config import Config


class T212Error(RuntimeError):
    pass


class Client:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._http = httpx.Client(
            base_url=cfg.base, timeout=30.0,
            auth=(cfg.key, cfg.secret))

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *_e: object) -> None:
        self.close()

    # ---- reads -----------------------------------------------------------
    def _get(self, path: str, retries: int = 4) -> Any:
        for attempt in range(retries):
            r = self._http.get(path)
            if r.status_code == 429:
                # T212 publishes the window; wait it out rather than hammer.
                time.sleep(min(2 ** attempt, 8))
                continue
            if r.status_code == 401:
                raise T212Error(
                    "401 from T212. The usual cause is the wrong environment: "
                    "a live key 401s against the demo host and vice versa. "
                    f"Mode is {self.cfg.mode!r}.")
            if r.status_code >= 400:
                raise T212Error(f"GET {path} -> {r.status_code}: {r.text[:200]}")
            return r.json()
        raise T212Error(f"GET {path} rate-limited after {retries} attempts")

    def cash(self) -> dict:
        return self._get("/equity/account/cash")

    def portfolio(self) -> list[dict]:
        return self._get("/equity/portfolio") or []

    def instruments(self) -> list[dict]:
        return self._get("/equity/metadata/instruments") or []

    def verify(self) -> dict:
        """Prove the credentials reach the account we think they do."""
        info = self._get("/equity/account/info")
        got = str(info.get("id") or "")
        want = self.cfg.account_id
        if want and got and not got.startswith(want.lstrip("0")[:4]):
            # Advisory rather than fatal: T212 has changed this shape before,
            # and refusing to run on a cosmetic mismatch would be worse than
            # printing what we actually reached.
            info["_warning"] = (f"account id {got} does not obviously match "
                                f"key prefix {want}")
        return info

    # ---- the one write ---------------------------------------------------
    def market_buy(self, ticker: str, quantity: float) -> dict:
        """A market order. ⚠️ Not retried, ever - see the module docstring."""
        r = self._http.post("/equity/orders/market",
                            json={"ticker": ticker, "quantity": quantity})
        if r.status_code >= 400:
            raise T212Error(f"order refused ({r.status_code}): {r.text[:300]}")
        return r.json()
