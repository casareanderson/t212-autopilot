# Setting up t212-autopilot

Read this first: **use the Trading 212 demo account.** Nothing in this repo shows the signals make money.
The numbers in the README say the opposite, and the defaults (demo mode, a £100 ceiling, only 10% on
picks) are set for that reason. This is a tool for running a plan you've already tested, not a way to
make one work. It isn't financial advice.

About 15 minutes. The steps marked **CI checks this** run every week on a fresh Ubuntu machine by
[`setup-check`](../.github/workflows/setup-check.yml), against a **fake** Trading 212 API
([`scripts/fake_t212.py`](../scripts/fake_t212.py)). CI never touches a real account.

## What you need

| | |
|---|---|
| OS | anything with Python |
| Python | 3.10 or newer (CI runs 3.10 and 3.12) |
| Python packages | `httpx` (the only dependency) |
| Broker | a Trading 212 account with the API enabled. Start with the **demo** (practice) account. |
| A picks feed | a JSON file or https URL listing what you'd consider buying. This repo deliberately has no scanner. `picks.example.json` shows the shape. |
| Optional | a Grok (xAI) API key. It only re-orders picks that have already passed the rules. |

## 1. Install (CI checks this)

```bash
git clone https://github.com/casareanderson/t212-autopilot && cd t212-autopilot
python3 -m pip install -r requirements.txt
python3 -m autopilot --help
```

Without a key, every command stops with a clear message and exit code 1:

```
  ✗ T212_KEY and T212_SECRET must both be set (auth is HTTP Basic - the key is the username, the secret is the password)
```

## 2. Get a demo API key (not checked by CI)

1. In the Trading 212 app or web dashboard, **switch to the practice (demo) account**.
2. **Settings → API (Beta) → Generate API key.** Generate it on the account you mean to use: a demo key
   gets `401` from the live host and a live key gets `401` from the demo host. A 401 almost always means
   the wrong account, not a bad key.
3. Give it read access. Add order placement only when you get to step 6.
4. Copy the key and the secret.

## 3. Configure

```bash
cp .env.example .env      # then fill in T212_KEY and T212_SECRET
chmod 600 .env
set -a; . ./.env; set +a
```

`.env` is git-ignored. Every setting:

| name | default | what it does |
|---|---|---|
| `T212_MODE` | `demo` | `demo` or `live`. Anything else is refused (CI checks this). |
| `T212_KEY`, `T212_SECRET` | none | the API key and secret (HTTP Basic). The key's first 8 characters are the account number. |
| `AUTOPILOT_STAKE_GBP` | `100` | ceiling on everything this tool holds and buys, in GBP |
| `AUTOPILOT_SAFE_SHARE` | `0.90` | share of the budget for the ETF sleeve |
| `AUTOPILOT_SAFE_TICKERS` | `VUAG_EQ,VWRP_EQ,ISF_EQ` | the ETFs for the safe sleeve, split equally |
| `AUTOPILOT_MAX_RISK_POSITIONS` | `4` | most picks bought in one run |
| `AUTOPILOT_MIN_HIT_RATE` | `0.60` | picks below this recorded hit rate are skipped |
| `GROK_API_KEY` | none | optional. Turns on Grok re-ordering. |
| `GROK_MODEL` | `grok-4-latest` | model used for re-ordering |
| `AUTOPILOT_TENANTS` | `tenants.json` | customer file for `serve` (step 7) |

## 4. Check it reaches the right account (CI checks this against the fake)

```bash
python3 -m autopilot check
```

Success:

```
mode: demo   stake ceiling: £100.00   split: 90% safe / 10% risk
  account : 12345678 (GBP)
  free    : £...
  invested: £...
  ok - credentials reach this account
```

If the key's prefix doesn't match the account it reached, you'll see a `⚠️ account id ... does not
obviously match key prefix ...` line. Stop and check which account the key belongs to.

## 5. Plan (CI checks it sends nothing)

```bash
python3 -m autopilot plan --picks picks.example.json
```

`plan` never writes. It prints which picks were skipped and why (a stop missing or above entry, a hit
rate under the floor), then a table: sleeve, ticker, quantity, £ and the reason, and ends with
`plan only - nothing was sent`.

**Expect the ETF sleeve to skip ETFs you don't already hold** (`VWRP_EQ: no price available - skipped`).
Trading 212's public API has no price endpoint, so the tool can only price ETFs you hold. Buy a small
amount of each by hand first if you want that sleeve to work.

`--picks` takes a local file or an **https** URL. A plain `http://` feed is refused (CI checks this), and so
is any URL that resolves to a private address.

## 6. Apply on demo (CI checks it against the fake)

Give the key order placement, then:

```bash
python3 -m autopilot apply --picks picks.example.json
```

It prints the plan first, then one `placed <ticker> x<qty> -> <order id>` line per order. Market orders
only, buys only. **Orders are never retried**: Trading 212 has no idempotency key, so a retry would be a
second order. A refused order is reported and the rest of the plan carries on.

Run it on demo for long enough to judge your own feed. The README explains why that matters.

### Live

Only when your own demo record says so: a live key, `T212_MODE=live`, and `--yes-live` typed on the
command. Without the flag, live mode prints the plan and stops with
`REFUSED: mode is live and --yes-live was not given` (exit 2). CI checks that refusal, and that nothing
reaches the broker.

## 7. Optional: run it for someone else over MCP (CI checks the auth)

```bash
python3 -m autopilot new-token        # prints tok_...
```

Put each person in `tenants.json` (never commit it):

```json
{"tok_...": {"name": "Alex", "t212_key": "...", "t212_secret": "...",
             "mode": "demo", "stake_gbp": 250, "safe_share": 0.9}}
```

```bash
AUTOPILOT_TENANTS=tenants.json python3 -m autopilot serve --port 8790
```

`GET /health` answers without a token. `initialize` and `tools/list` do too, so a client can discover it.
**Every tool call needs `Authorization: Bearer tok_...`**: no token or a wrong one gets
`not authorised for this server` (CI checks both). The tools are `cash`, `positions`, `plan` and
`apply_demo`. There is no live buy over MCP at all.

`serve` speaks plain HTTP. Put it behind a TLS reverse proxy before anyone else can reach it. If you run
this for other people, you may need regulatory cover where you are. Check before you do.

## Common errors

| you see | what's wrong |
|---|---|
| `T212_KEY and T212_SECRET must both be set` | `.env` not loaded into this shell. Run `set -a; . ./.env; set +a`. |
| `401 from T212. The usual cause is the wrong environment` | a demo key in live mode or the other way round |
| `T212_MODE must be 'demo' or 'live'` | typo in `T212_MODE` |
| `<ETF>: no price available - skipped` | you don't hold that ETF yet (see step 5) |
| `hit rate 0.19 below 0.60 - skipped` | working as intended: the pick is under `AUTOPILOT_MIN_HIT_RATE` |
| `picks feed must be an https URL` | use https, or a local file |
| `GET ... rate-limited after 4 attempts` | Trading 212's rate limit. Wait a minute. |
| `order refused (400): ...` | Trading 212 rejected that order (market closed, quantity too small, instrument not tradable). The rest of the plan still ran. |

## Updating and uninstalling

```bash
git pull && python3 -m pip install -r requirements.txt
```

`.env` and `tenants.json` stay put. To remove it: delete the folder, and revoke the API key in Trading 212
(Settings → API).

## What CI can't prove

Every week CI runs the CLI against a fake broker: missing and bad settings are refused, `check` reads an
account, `plan` sends nothing, demo `apply` sends the planned orders, live `apply` refuses without
`--yes-live`, plain-http feeds are refused, and the MCP server refuses tool calls without the right token.
It can't prove Trading 212's real API still answers the same way, that your orders fill, what Grok does
with your picks, or anything about returns.
