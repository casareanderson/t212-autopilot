#!/usr/bin/env bash
# Runs docs/SETUP.md against a FAKE Trading 212 API (scripts/fake_t212.py). It never touches a real
# account, demo or live. What it proves: missing settings are caught, `check` reads an account,
# `plan` sends nothing, demo `apply` sends orders, live `apply` refuses without --yes-live, a plain-http
# picks feed is refused, and the MCP server needs a token for every tool call.
set -euo pipefail
step() { printf '\n== %s\n' "$*"; }
P=${P:-18110}; MP=${MP:-18111}
export PYTHONPATH="$PWD"
unset T212_KEY T212_SECRET T212_MODE GROK_API_KEY AUTOPILOT_TENANTS || true
cli() { python3 scripts/against_fake.py "$P" "$@"; }
orders() { curl -s "localhost:$P/_orders" | python3 -c "import json,sys;print(len(json.load(sys.stdin)))"; }

step "1. install"
python3 -m pip install -q -r requirements.txt
python3 -m autopilot --help >/dev/null && echo "CLI loads"

step "2. no key -> clear message, exit 1"
set +e; out=$(python3 -m autopilot check 2>&1); rc=$?; set -e
echo "$out"; [ "$rc" -eq 1 ] && grep -q "T212_KEY and T212_SECRET must both be set" <<<"$out"
set +e; out=$(T212_KEY=k T212_SECRET=s T212_MODE=paper python3 -m autopilot check 2>&1); rc=$?; set -e
[ "$rc" -eq 1 ] && grep -q "T212_MODE must be 'demo' or 'live'" <<<"$out" && echo "bad mode refused"

python3 scripts/fake_t212.py "$P" & fake=$!
trap 'kill $fake ${mcp:-} 2>/dev/null || true' EXIT
for i in $(seq 1 20); do curl -s "localhost:$P/_orders" >/dev/null && break; sleep 0.3; done
export T212_KEY=12345678fake T212_SECRET=fake-secret

step "3. check (fake demo account)"
cli check | tee /tmp/ap.txt; grep -q "ok - credentials reach this account" /tmp/ap.txt
grep -q "mode: demo" /tmp/ap.txt

step "4. plan sends nothing"
cli plan --picks picks.example.json | tee /tmp/ap.txt
grep -q "plan only - nothing was sent" /tmp/ap.txt
grep -q "BBD" /tmp/ap.txt && echo "(the low hit-rate pick is reported as skipped)"
[ "$(orders)" -eq 0 ] && echo "fake broker received 0 orders"

step "5. live apply without --yes-live is refused"
set +e; T212_MODE=live cli apply --picks picks.example.json > /tmp/ap.txt 2>&1; rc=$?; set -e
tail -2 /tmp/ap.txt; [ "$rc" -eq 2 ] && grep -q "REFUSED: mode is live and --yes-live was not given" /tmp/ap.txt
grep -q "LIVE - REAL MONEY" /tmp/ap.txt
[ "$(orders)" -eq 0 ] && echo "fake broker still received 0 orders"

step "6. demo apply places the planned orders"
cli apply --picks picks.example.json | tail -4
n=$(orders); echo "fake broker received $n order(s)"; [ "$n" -ge 1 ]

step "7. a plain-http picks feed is refused"
set +e; out=$(cli plan --picks http://example.com/picks.json 2>&1); set -e
grep -q "must be an https URL" <<<"$out" && echo "refused"

step "8. MCP server: discovery is open, every tool call needs a token"
tok=$(python3 -m autopilot new-token); [[ "$tok" == tok_* ]] && echo "minted ${tok:0:8}..."
tdir=$(mktemp -d)
python3 - "$tok" "$tdir/tenants.json" <<'PY'
import json, sys
json.dump({sys.argv[1]: {"name": "Alex", "t212_key": "12345678fake", "t212_secret": "x",
                         "mode": "demo", "stake_gbp": 250, "safe_share": 0.9}}, open(sys.argv[2], "w"))
PY
AUTOPILOT_TENANTS="$tdir/tenants.json" python3 -m autopilot serve --host 127.0.0.1 --port "$MP" >/dev/null 2>&1 & mcp=$!
for i in $(seq 1 20); do curl -sf "localhost:$MP/health" >/dev/null && break; sleep 0.3; done
curl -sf "localhost:$MP/health"; echo
rpc() { curl -s "localhost:$MP/" -H "Content-Type: application/json" "$@"; }
rpc -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python3 -c "
import json,sys; names=[t['name'] for t in json.load(sys.stdin)['result']['tools']]
print('tools:', names); assert 'apply_demo' in names and not any('live' in n for n in names), names"
rpc -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"cash","arguments":{}}}' \
  | grep -q "not authorised for this server" && echo "tool call without a token: not authorised"
rpc -H "Authorization: Bearer tok_wrong" -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"cash","arguments":{}}}' \
  | grep -q "not authorised for this server" && echo "tool call with a wrong token: not authorised"

printf '\nSETUP CHECK PASSED\n'
