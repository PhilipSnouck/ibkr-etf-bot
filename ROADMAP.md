# IBKR ETF Bot - Roadmap

Python bot that automates periodic ETF purchases across multiple Interactive Brokers accounts.
Run manually once per period via a local web dashboard: Preview → Execute. Safe by default, deterministic, transparent.
Built with Python 3.10+, FastAPI + SSE, ib_async, IBC for Gateway login. Runs locally on Philip's laptop.

- **Live:** localhost only (laptop)
- **GitHub:** https://github.com/PhilipSnouck/ibkr-etf-bot
- **Local:** `C:\Users\p.snouckaert\Personal repos\IBKR-bot-docs\IBKR-etf-bot`

---

# 🔥 Now

## Confirm VUAA fallback works live (S)

IBKR refuses VUAA on BVME.ETF with Error 354 intermittently, which killed the whole Pension
account because the bot had only one way to get a price. Root-causing the refusal went
nowhere across several sessions: market hours, Gateway timing and clientId reuse were all
ruled out, and the refusal is intermittent, which rules out a missing entitlement too. The
fix is resilience rather than diagnosis, and it is now built and tested offline.
Done when: a live run prices VUAA through one of the fallback rungs, or names which rung
failed and why.

- [x] Fallback chain: SMART routing, delayed frozen, historical close (M)
- [x] Offline regression test for all three shapes (`test_price_fallback.py`) (S)
- [ ] Run Preview All live and check which rung supplies VUAA (S)
- [ ] If every rung fails, compare VUAA on an alternative venue with data that works (S)

## Fix EGLN order rejection 478 (M)

Pension's EGLN order is cancelled by IBKR with Error 478, "requested ibLocalSymbol EGLN,
from contract PPFB". `place_order` routes via SMART by copying the qualified contract and
swapping the exchange, which leaves `localSymbol` and `tradingClass` from the LSEETF
listing attached to a request IBKR now resolves differently. Clearing those fields is the
obvious fix but must NOT be done blind: if the conId really does resolve to another
instrument under SMART, clearing the identifying fields would buy the wrong ETF with real
money. Verify what SMART resolves to before trusting it.
Done when: EGLN orders are accepted, and the bot refuses to place an order whose routed
contract does not match the one that was priced.

- [ ] Re-qualify the SMART-routed contract and log what IBKR resolves it to (S)
- [ ] Compare symbol, currency and conId against the priced contract, abort on mismatch (S)
- [ ] Only then decide whether to clear `localSymbol` / `tradingClass` (S)
- [ ] Check whether the same risk applies to the SMART rung in the price fallback chain (S)

## Review the execution path (M)

Three independent defects surfaced in a single live run on 2026-10-01: Error 478 on EGLN,
the cash-sizing rejection, and the dashboard showing a green "Ready" badge on an account
whose only order was rejected. Two were long-standing and simply had not met their trigger
conditions. That rate suggests the order and status path deserves a deliberate read rather
than another round of symptom chasing.
Done when: the execute path has been reviewed end to end and findings are either fixed or
written down here.

- [ ] Read `place_order`, `execute_plan` and the `pending_followup` branches end to end (M)
- [ ] Check every IBKR terminal status is handled in both the bot and the dashboard parser (S)
- [ ] Confirm `get_account_cash` should read `SettledCash` rather than `TotalCashValue` (S)
- [ ] `order_commission_buffer` is flat 1.25 EUR but IBKR charged ~3.10 on a 4.2k order; make it scale (S)

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
