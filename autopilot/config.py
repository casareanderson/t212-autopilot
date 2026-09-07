"""Every setting, read from the environment once, with safe defaults.

⚠️⚠️ THE DEFAULT IS THE DEMO ACCOUNT AND THAT IS NOT TIMIDITY. The signals this
follows were measured before this repo existed: the daily scan picks averaged
-0.187R over 213 graded picks, and the 4H blue/purple pattern averaged +1.93%
over 10 setups - of which one trade supplied all of it. Neither is an edge you
would knowingly automate with real money. Point it at `live` when your own
numbers say so, not because a README told you to.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

DEMO_BASE = "https://demo.trading212.com/api/v0"
LIVE_BASE = "https://live.trading212.com/api/v0"


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


@dataclass
class Config:
    mode: str = field(default_factory=lambda:
                      (os.environ.get("T212_MODE") or "demo").strip().lower())
    key: str = field(default_factory=lambda: os.environ.get("T212_KEY", "").strip())
    secret: str = field(default_factory=lambda: os.environ.get("T212_SECRET", "").strip())

    # The ceiling on everything this tool controls. Cash beyond it is not its
    # business, whatever lands in the account.
    stake_gbp: float = field(default_factory=lambda: _f("AUTOPILOT_STAKE_GBP", 100.0))
    # 90 / 10 by default: accumulation is the part with a real expected return.
    safe_share: float = field(default_factory=lambda: _f("AUTOPILOT_SAFE_SHARE", 0.90))
    max_positions_risk: int = field(default_factory=lambda:
                                    int(_f("AUTOPILOT_MAX_RISK_POSITIONS", 4)))
    # A pick below this recorded hit rate is not bought. Measured: picks under
    # 0.50 averaged -0.24R, picks at 0.60+ averaged -0.067R. Neither is
    # positive; this is damage limitation, not a filter that makes it work.
    min_hit_rate: float = field(default_factory=lambda: _f("AUTOPILOT_MIN_HIT_RATE", 0.60))

    safe_tickers: list[str] = field(default_factory=lambda: [
        t.strip() for t in (os.environ.get("AUTOPILOT_SAFE_TICKERS")
                            or "VUAG_EQ,VWRP_EQ,ISF_EQ").split(",") if t.strip()])

    grok_key: str = field(default_factory=lambda: os.environ.get("GROK_API_KEY", "").strip())
    grok_model: str = field(default_factory=lambda:
                            os.environ.get("GROK_MODEL", "grok-4-latest").strip())

    @property
    def base(self) -> str:
        return LIVE_BASE if self.mode == "live" else DEMO_BASE

    @property
    def risk_share(self) -> float:
        return max(0.0, 1.0 - self.safe_share)

    @property
    def account_id(self) -> str:
        """A T212 key's first 8 characters ARE the account number."""
        return self.key[:8]

    def problems(self) -> list[str]:
        """Everything wrong with this configuration, in one pass."""
        p = []
        if not self.key or not self.secret:
            p.append("T212_KEY and T212_SECRET must both be set "
                     "(auth is HTTP Basic - the key is the username, the "
                     "secret is the password)")
        if self.mode not in ("demo", "live"):
            p.append(f"T212_MODE must be 'demo' or 'live', not {self.mode!r}")
        if not 0.0 <= self.safe_share <= 1.0:
            p.append("AUTOPILOT_SAFE_SHARE must be between 0 and 1")
        if self.stake_gbp <= 0:
            p.append("AUTOPILOT_STAKE_GBP must be positive")
        return p
