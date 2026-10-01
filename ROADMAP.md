# IBKR ETF Bot - Roadmap

Python bot that automates periodic ETF purchases across multiple Interactive Brokers accounts.
Run manually once per period via a local web dashboard: Preview → Execute. Safe by default, deterministic, transparent.
Built with Python 3.10+, FastAPI + SSE, ib_async, IBC for Gateway login. Runs locally on Philip's laptop.

- **Live:** localhost only (laptop)
- **GitHub:** https://github.com/PhilipSnouck/ibkr-etf-bot
- **Local:** `C:\Users\p.snouckaert\Personal repos\IBKR-bot-docs\IBKR-etf-bot`

---

# 🔥 Now

## Stop the allocator refusing to invest (S)

The top-up trigger sets `chosen_shares = 0`, so when the fractional part of `raw_shares`
reaches 0.75 the account buys NOTHING, not just the one share it cannot afford. Correct for
Pension's ETF3 remainder leg (0 to 3 shares), badly wrong for a 100%-weight account where
`floor_shares` is 30+. Swept offline: 25% of single-ETF runs buy zero and leave an average
of 5032 EUR idle. This is why Samen investeren keeps buying nothing, and the Error 201 fix
of 2026-10-01 only changed the failure from a rejection into a silent skip.
Done when: an account buys what it can afford and tops up only for the remainder.

- [ ] Allocators buy `floor_shares` instead of 0; all-or-nothing only when `floor_shares == 0` (S)
- [ ] Pension ETF1 gets the same `while shares > 0` loop as ETF2 and ETF3; a negative share count is a hard stop (S)
- [ ] Move the tick snap in front of sizing: compute once in `main.py`, `place_order` asserts rather than adjusts (S)
- [ ] Extract `build_plan()` from `main.py` so the sweep tests the shipped path, not a re-implementation (M)
- [ ] `assert_affordable` must include the tick snap; the current invariant is false without it (S)

## Give the run error boundaries (M)

`main.py` catches one exception type for the whole run and the account loop has no per-account
boundary, so one account's bad state destroys every other account's approved orders. The
placement loop has no try/except at all: a drop between orders leaves live orders at IBKR with
nobody watching, no summary printed, and the handler then advises a re-run that would duplicate
them.
Done when: no single account or order can take down the rest of the run.

- [ ] try/except around each `place_order`, continue to status-watch and summary for what was sent (S)
- [ ] try/except around the per-account body in `main.py` (S)
- [ ] ConnectionError handler prints the transmitted orders and drops the "re-run" advice (S)
- [ ] Never skip the `pending_followup` bookkeeping because of a placement error (S)

## Make pending top-ups safe state (M)

Ten of the audit's findings are in this one subsystem. It is the only state carried between
runs and it was built without the defences the stateless path has: no validation on load, no
environment key, no reconciliation against what was actually bought, no None guards, no gate
checks, and it mutates on preview.
Done when: a pending file cannot cause a double purchase, a crash, or a paper/live crossover.

- [ ] Reconcile against `trade.orderStatus.filled`; refuse to re-place while an order is open at IBKR (M)
- [ ] Environment in the filename, and refuse on `account_id` mismatch (S)
- [ ] Validate the record on load; a bad one is a safety stop for that account only (S)
- [ ] Guard the `real_cash is None` path, which currently crashes the whole run (S)
- [ ] Preview must not delete or mutate pending state (S)

---

# 🚀 Next Build

## Phone access via always-on host (L)

The dashboard runs on localhost only, so the bot can only be used at the laptop.
Move it to an always-on machine so Philip can run Preview → Execute from his phone browser.
Decision needed first: which host. Done when: Philip can open the dashboard and execute a run from his phone.

- [ ] Decide host: VPS (e.g. Hetzner/DigitalOcean) vs Raspberry Pi vs Mac mini - weigh cost, uptime, MFA/Gateway reliability, and whether IB Gateway runs well on it
- [ ] Provision the chosen host and install Python + dependencies + IBC + IB Gateway
- [ ] Get IB Gateway + IBC running headless on the host (no desktop session)
- [ ] Bind the FastAPI server to the network; put it behind HTTPS + auth (reverse proxy or Tailscale)
- [ ] Lock down access - never expose the dashboard or Gateway API to the open internet without auth
- [ ] Test full Preview → Execute round-trip from the phone, including the MFA approval flow
- [ ] Document the host setup and restart procedure in README

## Retry for unfilled limit orders (M)

Currently if a limit order times out (2 min) and stays open at IBKR, the bot warns and stops - Philip must check TWS manually.
Add a controlled retry so a near-miss fill doesn't require manual intervention.
Done when: an unfilled order is re-priced and retried a bounded number of times, then reported clearly.

- [ ] Detect the open/unfilled order after timeout
- [ ] Cancel and re-place at an updated limit price (bounded markup)
- [ ] Cap retries; surface final state in the dashboard card
- [ ] Never double-place - confirm cancellation before re-placing

---

# 🔮 Future

- [ ] Scheduled / automated runs (M)
  Let the bot run on a schedule (e.g. monthly) instead of manual trigger only. Depends on always-on host being in place first. Keep the preview-then-execute safety model - auto-execute needs careful guardrails.

- [ ] Dynamic commission from IBKR (S)
  `order_commission_buffer` is a manual static setting. Fetch the real commission from IBKR instead of reserving a fixed EUR amount per order.

---

# ✅ Done

## Route orders by contract id (S)

IBKR cancelled Pension's EGLN order with Error 478, "requested ibLocalSymbol EGLN, from
contract PPFB". `place_order` copied the qualified contract and swapped only the exchange,
leaving `localSymbol` and `tradingClass` from the LSEETF listing attached. One ETF is listed
as several lines with different values for those fields, so the request contradicted itself.
SMART is a routing destination, not an instrument chooser, and `conId` already identifies the
instrument uniquely.
Done when: EGLN orders are accepted, and the bot cannot place an order on an instrument other
than the one it priced.

- [x] Build the routing contract from `conId` + SMART + currency, dropping venue fields (S)
- [x] Ask IBKR what the routed contract resolves to and verify conId, symbol and currency (S)
- [x] Refuse to place the order on any mismatch rather than trusting the resolution (S)
- [x] Send the minimal contract, not IBKR's resolved copy, which refills venue fields (S)
- [x] Offline test covering wrong-instrument, wrong-currency and unqualified cases (S)
- [ ] Confirm live that an EGLN order is accepted

## Size orders at the limit price (S)

IBKR rejected orders with Error 201, "Available settled cash ... Cash needed for this
order". The allocators counted shares at the last traded price while the order was placed
at price x (1 + markup), so IBKR reserved more cash than the plan assumed. A sweep of the
danger band shows 34.8% of plans would have been rejected, which is the "it works
sometimes" that made this so hard to pin down. `main.py` now derives `order_prices` once
and hands those to the allocator, so the cash arithmetic and the order can never diverge
again. The markup keeps doing its real job, which is making a delayed-price limit fill.
Done when: no plan can produce an order costing more cash than the account holds.

- [x] Size against `calc_limit_price(price, markup)`, derived once in `main.py` (S)
- [x] Allocators stay pure functions, no signature change needed (S)
- [x] Regression test on the live 4261.40 / 128.71 rejection (`test_order_sizing.py`) (S)
- [x] Sweep 1900 plans across the danger band and assert none exceeds cash (S)

## Report rejected orders honestly (S)

An account whose only order came back `Inactive` (how IBKR reports a rejection) kept its
green "Ready" badge, because the dashboard counted only statuses containing "cancel" and
the badge logic had no final else. The run summary missed it too. Rejections were therefore
invisible in the UI and only findable in the raw log.
Done when: any order that is not Filled is visible as a failure.

- [x] Treat every non-Filled terminal status as a failure, not just "cancel" (S)
- [x] Add the missing else so a card can never keep a stale "Ready" badge (S)
- [x] Reword the run summary from "cancelled" to "not filled" (S)

## Market data diagnostics (S)

Every price failure used to surface as one line, "no valid market price available for X",
which said nothing about whether IBKR refused the request, sent an empty tick, or was not
ready yet. Each occurrence cost a round of guesswork between market hours, entitlements and
Gateway state. A failed fetch now prints the contract, the connection (clientId and run
mode), market hours, the per-pass ticker fields, the IBKR messages received, the market data
farm status, and what each code means. Observation only: it never changes which price the
bot uses.
Done when: a failed fetch is diagnosable from the log alone.

- [x] `price_diagnostics.py` collector attached to `errorEvent` at connect, before any sleep (S)
- [x] Capture farm status codes and compare their order against the fetch, which separates "data session not ready" from "not entitled" (S)
- [x] Per-pass record of marketPrice / last / bid / ask / close and the data type actually received (S)
- [x] One summary line on every fetch showing the data type and quote field each price came from (S)
- [x] Plain-language hints for 354, 300, 201, 110, 326 and the other codes this bot hits (S)
- [x] Offline simulation of both failure shapes, no Gateway needed (S)

## Tick-conforming limit prices (S)

IBKR cancelled orders with Error 110, "the price does not conform to the minimum price
variation for this contract". Limit prices are now snapped **up** to a valid tick read from
the market rule of the venue the order is actually routed to (SMART), per price band,
instead of from `minTick` or the listing exchange.
Done when: no ETF in the config can produce a non-conforming limit price.

- [x] Round limit prices up to a valid tick with Decimal arithmetic (`round_up_to_tick`)
- [x] Read the per-band increment from the contract's market rule instead of `minTick`
- [x] Use the market rule of the routed venue (SMART), not the listing exchange (fixes IMAE, which is 0.005 on AEB but 0.02 on SMART between EUR 100 and 200)
- [x] Set `primaryExchange` in `place_order` instead of the non-existent `primaryExch`
- [x] Offline regression test with frozen IBKR market-rule data (`test_tick_conformance.py`)

## Core bot engine (L)
- [x] Per-account flow: connect → read cash → fetch prices → allocate → check rules → preview → execute
- [x] Allocator / Rules / Broker split - what to buy / whether to buy / how to buy
- [x] Allocator registry mapping names to strategy functions
- [x] Pension allocator (3 ETFs by target weight, rounding rules)
- [x] Joint + Otto allocators (100% into a single ETF)
- [x] Deterministic - same inputs always produce the same plan

## Order execution (M)
- [x] Limit orders at price × (1 + markup), default 0.5% buffer
- [x] Simultaneous order placement across all ETFs in an account
- [x] Waits up to 2 min for fills, warns and stops if not confirmed
- [x] Market-hours + safety-rule checks before placing

## Top-up system (M)
- [x] Skips tiny orders when close to affording the next share (fractional ≥ topup_trigger)
- [x] Persistent account-specific `pending_topup_{account}.json` files
- [x] Auto-expire after 7 days (configurable)
- [x] Suggested deposit uses limit price to match required cash
- [x] Status messages surfaced in the dashboard card
- [x] Pending file only saved after all other orders fill; preview never writes files

## Web dashboard (L)
- [x] FastAPI server with SSE streaming of bot output
- [x] Accounts panel showing ETFs and target weights
- [x] Preview all - per-account cards (cash, allocation rows, top-up status, remaining cash)
- [x] Execute all - enabled after successful preview, gated on green Gateway indicator
- [x] Raw log toggle for debugging
- [x] Settings page - edit all config without touching code
- [x] `IBKR_dashboard.bat` desktop shortcut launches server + opens browser

## IBC / Gateway integration (M)
- [x] Auto-start IB Gateway via IBC when not already running
- [x] MFA-on-phone login flow with retry (~50s)
- [x] Gateway connection indicator turns green on first successful connect
- [x] Auto-shutdown Gateway on browser tab close (avoids nightly-restart MFA)
- [x] Credentials in `IBC/config.ini`, excluded from git

## Configuration + safety (M)
- [x] Single source of truth: `config_store.json`, read at runtime, written by Settings page
- [x] `planned_allocation_cash` cap with execute-mode safety stop if cap > real cash
- [x] Paper/live environment switch; execution_mode preview/live guard
- [x] Full safety-check matrix (price unavailable, market closed, min cash, Gateway not connected)

---

# 📝 Notes

### Code structure
```
server.py                # FastAPI server - dashboard API and SSE streaming
main.py                  # Bot orchestrator - loops through accounts
account_processor.py     # Per-account flow and execution logic
broker.py                # IBKR connection, price fetching, order placement
rules.py                 # Config-driven rule evaluation
config.py                # Loads settings from config_store.json
config_store.json        # Single source of truth for all settings
allocator_*.py           # Strategy functions + registry
pending_topup.py         # Persistent state for incomplete trades
test_tick_conformance.py # Offline Error 110 regression test (no Gateway, no orders)
dashboard/               # index.html (preview+execute) + settings.html
IBKR_dashboard.bat      # Double-click to start server + open browser
```

### Audit of 2026-10-01

A 275-agent sweep audited every module, with three adversarial verifiers per finding: 64 raised,
20 refuted, 56 confirmed (4 critical, 29 high, 23 medium). Verdict: no rewrite needed, the
architecture is sound, but the defects are concentrated in the allocators, the pending top-up
subsystem and the missing error paths. Five root causes explain almost all of them:

1. Pending top-up is unguarded persistent state (10 findings)
2. Error paths were never written, so every failure is a total failure
3. Things that must agree are computed twice independently (sizing vs placement, preview vs execute)
4. The bot's stdout is a protocol parsed by per-symptom regexes, so correct output gets dropped
5. The tests re-implement the code instead of calling it, so both suites stay green if their fix is reverted

Most defects are cliff-shaped: a fraction crossing 0.75, a leftover smaller than one tick, a
conId seen before in the same process. None are random, all look random, none are visible in a
log that reports success. That is the whole "run of intermittent bugs".

### Known limitations (current)
- No retry for unfilled limit orders (see Next Build)
- No persistent file logging
- No FX handling - assumes account currency matches ETF currency
- Static commission buffer, not fetched from IBKR (see Future)
- Localhost only - phone access needs an always-on host (see Next Build)

### Ports
Live Gateway `4001`, paper `4002`. API access must be enabled in Gateway settings.

### Deploy / run flow
```bash
pip install -r requirements.txt
# Double-click "IBKR ETF Bot" desktop shortcut (or run IBKR_dashboard.bat)
# Opens http://localhost:9000 - Preview → Execute
```
