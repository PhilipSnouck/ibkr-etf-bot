# IBKR ETF Bot — Roadmap

Python bot that automates periodic ETF purchases across multiple Interactive Brokers accounts.
Run manually once per period via a local web dashboard: Preview → Execute. Safe by default, deterministic, transparent.
Built with Python 3.10+, FastAPI + SSE, ib_insync, IBC for Gateway login. Runs locally on Philip's laptop.

- **Live:** localhost only (laptop)
- **GitHub:** https://github.com/PhilipSnouck/ibkr-etf-bot
- **Local:** `C:\Users\p.snouckaert\Own AI projects\IBKR-bot-docs\IBKR-etf-bot`

---

# 🔥 Now

*(nothing active right now)*

---

# 🚀 Next Build

## Phone access via always-on host (L)

The dashboard runs on localhost only, so the bot can only be used at the laptop.
Move it to an always-on machine so Philip can run Preview → Execute from his phone browser.
Decision needed first: which host. Done when: Philip can open the dashboard and execute a run from his phone.

- [ ] Decide host: VPS (e.g. Hetzner/DigitalOcean) vs Raspberry Pi vs Mac mini — weigh cost, uptime, MFA/Gateway reliability, and whether IB Gateway runs well on it
- [ ] Provision the chosen host and install Python + dependencies + IBC + IB Gateway
- [ ] Get IB Gateway + IBC running headless on the host (no desktop session)
- [ ] Bind the FastAPI server to the network; put it behind HTTPS + auth (reverse proxy or Tailscale)
- [ ] Lock down access — never expose the dashboard or Gateway API to the open internet without auth
- [ ] Test full Preview → Execute round-trip from the phone, including the MFA approval flow
- [ ] Document the host setup and restart procedure in README

## Retry for unfilled limit orders (M)

Currently if a limit order times out (2 min) and stays open at IBKR, the bot warns and stops — Philip must check TWS manually.
Add a controlled retry so a near-miss fill doesn't require manual intervention.
Done when: an unfilled order is re-priced and retried a bounded number of times, then reported clearly.

- [ ] Detect the open/unfilled order after timeout
- [ ] Cancel and re-place at an updated limit price (bounded markup)
- [ ] Cap retries; surface final state in the dashboard card
- [ ] Never double-place — confirm cancellation before re-placing

---

# 🔮 Future

- [ ] Scheduled / automated runs (M)
  Let the bot run on a schedule (e.g. monthly) instead of manual trigger only. Depends on always-on host being in place first. Keep the preview-then-execute safety model — auto-execute needs careful guardrails.

- [ ] Dynamic commission from IBKR (S)
  `order_commission_buffer` is a manual static setting. Fetch the real commission from IBKR instead of reserving a fixed EUR amount per order.

- [ ] FX handling (M)
  Bot assumes account currency matches ETF currency. Handle the case where they differ (currency conversion or cross-currency orders).

- [ ] Persistent file logging (S)
  All output currently streams to the dashboard only and is lost when the session ends. Write runs to a persistent log file for audit and debugging.

---

# ✅ Done

## Core bot engine (L)
- [x] Per-account flow: connect → read cash → fetch prices → allocate → check rules → preview → execute
- [x] Allocator / Rules / Broker split — what to buy / whether to buy / how to buy
- [x] Allocator registry mapping names to strategy functions
- [x] Pension allocator (3 ETFs by target weight, rounding rules)
- [x] Joint + Otto allocators (100% into a single ETF)
- [x] Deterministic — same inputs always produce the same plan

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
- [x] Preview all — per-account cards (cash, allocation rows, top-up status, remaining cash)
- [x] Execute all — enabled after successful preview, gated on green Gateway indicator
- [x] Raw log toggle for debugging
- [x] Settings page — edit all config without touching code
- [x] `start_dashboard.bat` desktop shortcut launches server + opens browser

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
server.py                # FastAPI server — dashboard API and SSE streaming
main.py                  # Bot orchestrator — loops through accounts
account_processor.py     # Per-account flow and execution logic
broker.py                # IBKR connection, price fetching, order placement
rules.py                 # Config-driven rule evaluation
config.py                # Loads settings from config_store.json
config_store.json        # Single source of truth for all settings
allocator_*.py           # Strategy functions + registry
pending_topup.py         # Persistent state for incomplete trades
dashboard/               # index.html (preview+execute) + settings.html
start_dashboard.bat      # Double-click to start server + open browser
```

### Known limitations (current)
- No retry for unfilled limit orders (see Next Build)
- No persistent file logging (see Future)
- No FX handling — assumes account currency matches ETF currency (see Future)
- Static commission buffer, not fetched from IBKR (see Future)
- Localhost only — phone access needs an always-on host (see Next Build)

### Ports
Live Gateway `4001`, paper `4002`. API access must be enabled in Gateway settings.

### Deploy / run flow
```bash
pip install -r requirements.txt
# Double-click "IBKR ETF Bot" desktop shortcut (or run start_dashboard.bat)
# Opens http://localhost:8000 — Preview → Execute
```
