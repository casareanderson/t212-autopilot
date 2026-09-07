# t212-autopilot

Connects a **Trading 212** account to a picks feed you publish, and buys on a
fixed **90 / 10** split: 90% accumulation into broad ETFs, 10% following the
signal. Optionally lets **Grok** rank the candidates — inside an envelope it
cannot leave.

Defaults to the **demo** account. Read the next section before changing that.

---

## Read this before you point it at real money

This tool follows a signal. Whether it makes money depends entirely on whether
that signal is any good, so here is what measurement of the reference
implementation actually showed:

| signal | sample | result |
|---|---|---|
| daily scan picks | **213 graded picks** | **−0.187R average**, 43% win rate |
| 4H blue/purple pattern | **10 resolved setups** | **+1.93% average**, 5 winners |

And two details that matter more than the headlines:

- The pattern strategy's entire positive average comes from **one trade**.
  Remove it and the same ten setups average **−1.17%**.
- Its first measurement said +9.5% with 5 wins from 6 — because setups that
  expired without completing were **never assigned an exit price**, so the
  losing half of the strategy was invisible. Priced properly, all four expiries
  were losses of −6.1% to −12.6%.

A **stop-loss does not fix it.** Replayed against the real 4-hour bars:

| stop | average | stopped out |
|---|---|---|
| none | +1.93% | 0/10 |
| −5% | −1.29% | **7/10** |
| −7% | +0.99% | 6/10 |
| −10% | +1.01% | 5/10 |

Every stop level is worse than none, because the entry is *deliberately* a
failed bounce — these names dip hard before they turn. Tolerating drawdown is
the strategy, which means positions must be sized for a −10% adverse move.

**That is why the risk sleeve is 10% and the default account is demo.** Neither
is caution for its own sake; both are what the numbers support. Use the demo
account until your own feed shows a positive expectancy on a sample you would
defend.

Nothing here is financial advice, and no part of it predicts anything.

---

## Connecting Trading 212

1. In the T212 app or web dashboard: **Settings → API (Beta) → Generate API key**.
2. Generate the key **on the account you intend to trade**. A live key returns
   `401` against the demo host and a demo key returns `401` against the live
   host — that 401 is almost always the wrong environment, not a bad key.
3. Give the key **read** scope plus **order placement** if you intend to use
   `apply`. `check` and `plan` need only read.
4. Put both halves in your environment. Auth is **HTTP Basic**: the API key is
   the username, the secret is the password.

```bash
cp .env.example .env      # then fill it in
set -a; source .env; set +a
pip install -r requirements.txt
python -m autopilot check
```

`check` proves the credentials reach the account you think they do — it prints
the account id, currency and free cash, and warns if the id does not match the
key. **A T212 key's first 8 characters are the account number**, which is what
makes that check possible.

## Connecting Grok

Optional. Get a key from the xAI console and set `GROK_API_KEY`. With no key
the picks keep the order your feed gave them, and every safety property is
identical.

**What Grok is allowed to do:** reorder a list of candidates that have already
passed the mechanical filter.

**What it cannot do:** add a name, remove one, change a size, or move a stop.
The returned ranking is intersected back against the approved list, so an
invented ticker is impossible rather than merely unlikely. Sizing and stops are
arithmetic and live in `policy.py`.

This is not distrust of one vendor. The system this was extracted from lost
**£424** running LLM-driven trading flows, and the deterministic rebuild that
replaced them is the only reason there is anything worth automating. A model
that reorders four pre-screened names cannot repeat that. A model that chooses
what to buy can.

## The picks feed

A JSON file or an https URL. Publish it from whatever produces your signals —
this repo deliberately contains **no scanner**, so the thing that decides what
to buy and the thing that buys it can be replaced independently.

```json
[{"ticker": "AAON_US_EQ", "symbol": "AAON", "entry": 85.80, "stop": 78.19,
  "target": 94.38, "hit_rate": 0.62, "note": "blue-purple 4H"}]
```

`ticker` is the **broker's** ticker, not the exchange symbol. `stop` is
required — a pick without a usable stop is skipped. `hit_rate` is your
strategy's own measured hit rate for that kind of setup; anything below
`AUTOPILOT_MIN_HIT_RATE` is not bought.

## Using it

```bash
python -m autopilot check                      # credentials and account
python -m autopilot plan  --picks picks.json   # what it WOULD do. Never writes.
python -m autopilot apply --picks picks.json   # demo: places orders
python -m autopilot apply --picks picks.json --yes-live   # live: required
```

`apply` always prints the plan first. On the live account it additionally
refuses without `--yes-live`, because an environment variable set weeks ago is
not consent.

## The rules it enforces

1. **The stake is a ceiling.** Everything held plus everything about to be
   bought stays under `AUTOPILOT_STAKE_GBP`, whatever else is in the account.
   Money paid in tomorrow does not become this tool's to spend.
2. **No exit, no entry.** A pick without a usable stop is skipped.
3. **Nothing is bought that is not already qualified.** The model only reorders.
4. **Writes are never retried.** T212 has no idempotency key, so a retried
   `POST` is a second order, not the same one.
5. **An empty risk sleeve is a valid outcome.** If nothing qualifies, that
   tenth stays in cash and the run reports it rather than lowering the bar.

## Licence

MIT.
