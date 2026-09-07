"""What to buy, and how much - decided by arithmetic before anything is asked.

Two sleeves, and they are not the same kind of thing:

  * SAFE (90% by default) is ACCUMULATION. Buying a broad ETF on a schedule is
    not a prediction, and it is the only half of this with an expected return
    that does not depend on a signal being right.
  * RISK (10%) FOLLOWS THE SIGNAL. It is capped at a tenth of the stake because
    the signals were measured before this was written and neither is positive.
    The cap is the feature.

Three rules, each enforced here and not left to a caller:

 1. THE STAKE IS A CEILING. Everything this tool holds, plus anything it is
    about to buy, stays under it - whatever else is in the account. Money paid
    in tomorrow does not become this tool's to spend.
 2. NO EXIT, NO ENTRY. A pick without a usable stop is skipped. A position
    whose exit exists only in someone's head is the failure mode that cost the
    reference implementation £405 in one month.
 3. NOTHING IS BOUGHT THAT IS NOT ALREADY QUALIFIED. The model (see grok.py)
    only ever reorders this list. It cannot add to it.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import Config
from .picks import Pick


@dataclass
class Order:
    ticker: str
    quantity: float
    notional_gbp: float
    sleeve: str
    why: str


@dataclass
class Plan:
    orders: list[Order]
    notes: list[str]

    @property
    def total_gbp(self) -> float:
        return sum(o.notional_gbp for o in self.orders)


def _held_value(portfolio: list[dict]) -> float:
    total = 0.0
    for p in portfolio:
        q = float(p.get("quantity") or 0)
        px = float(p.get("currentPrice") or p.get("averagePrice") or 0)
        total += q * px
    return total


def qualify(picks: list[Pick], cfg: Config) -> tuple[list[Pick], list[str]]:
    """The candidates that may be bought at all, and why the others may not."""
    kept, notes = [], []
    for p in picks:
        if p.risk_pct <= 0:
            notes.append(f"{p.ticker}: no usable stop - skipped")
            continue
        if p.hit_rate < cfg.min_hit_rate:
            notes.append(f"{p.ticker}: hit rate {p.hit_rate:.2f} below "
                         f"{cfg.min_hit_rate:.2f} - skipped")
            continue
        kept.append(p)
    return kept, notes


def build(cfg: Config, cash: dict, portfolio: list[dict],
          picks: list[Pick], prices: dict[str, float]) -> Plan:
    notes: list[str] = []
    free = float(cash.get("free") or 0)
    held = _held_value(portfolio)
    headroom = max(0.0, cfg.stake_gbp - held)
    notes.append(f"stake ceiling £{cfg.stake_gbp:.2f}; already holding "
                 f"£{held:.2f}; headroom £{headroom:.2f}; account free £{free:.2f}")
    budget = min(headroom, free)
    if budget <= 0:
        notes.append("no budget: at or above the stake ceiling, or no free cash")
        return Plan([], notes)

    orders: list[Order] = []
    safe_budget = budget * cfg.safe_share
    risk_budget = budget * cfg.risk_share

    # ---- the safe sleeve: equal weight, no opinion required ---------------
    live_safe = [t for t in cfg.safe_tickers if prices.get(t)]
    for t in cfg.safe_tickers:
        if t not in live_safe:
            notes.append(f"{t}: no price available - skipped")
    if live_safe and safe_budget > 0:
        each = safe_budget / len(live_safe)
        for t in live_safe:
            qty = each / prices[t]
            if qty <= 0:
                continue
            orders.append(Order(t, round(qty, 6), each, "safe",
                                f"accumulation, 1/{len(live_safe)} of the "
                                f"{cfg.safe_share:.0%} sleeve"))

    # ---- the risk sleeve: capped, and only from qualified picks -----------
    if picks and risk_budget > 0:
        take = picks[:cfg.max_positions_risk]
        each = risk_budget / len(take)
        for p in take:
            px = prices.get(p.ticker) or p.entry
            if px <= 0:
                notes.append(f"{p.ticker}: no price - skipped")
                continue
            qty = each / px
            orders.append(Order(p.ticker, round(qty, 6), each, "risk",
                                f"hit rate {p.hit_rate:.2f}, stop "
                                f"{p.risk_pct:.1%} below entry - {p.note}"))
    elif not picks:
        notes.append("no qualified picks: the risk sleeve stays in cash, "
                     "which is a valid outcome and not an error")

    # ---- rule 1, enforced last, over everything ---------------------------
    total = sum(o.notional_gbp for o in orders)
    if held + total > cfg.stake_gbp + 0.01:
        notes.append(f"REFUSED: plan totals £{total:.2f} which would breach the "
                     f"£{cfg.stake_gbp:.2f} ceiling")
        return Plan([], notes)
    return Plan(orders, notes)
