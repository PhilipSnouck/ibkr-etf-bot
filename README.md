# IBKR Multi-Account ETF Bot

## Overview

A Python bot that automates periodic ETF purchases across multiple Interactive Brokers (IBKR) accounts. You run it manually once per period — it calculates how many shares to buy based on available cash and target allocations, then places orders when you explicitly confirm.

Operated via a **local web dashboard** (no terminal needed). Double-click the desktop shortcut, open the browser, click Preview → Execute.

Designed to be:
- **Safe by default** — preview mode shows the full plan before anything is placed
- **Deterministic** — same inputs always produce the same plan
- **Transparent** — clean per-account summary cards with allocation details and top-up status

---

## How It Works

For each configured account, the bot:

1. Connects to IBKR (starts IB Gateway via IBC if not already running)
2. Reads available cash
3. Fetches current ETF prices
4. Runs the allocator → calculates how many shares to buy
5. Checks market hours and safety rules
6. Shows a preview
7. On Execute: places limit orders

### Order execution

All orders are **limit orders** placed at `price × (1 + markup)` (default: 0.5% above last price). This means:
- You pay at or below the limit price — never above it
- The markup gives a small buffer so the order fills even if the price ticks up slightly
- Orders are placed simultaneously across all ETFs in an account
- The bot waits up to 2 minutes for fills; if an order hasn't confirmed by then it warns you and stops — check TWS before re-running

### Code structure

```
server.py                # FastAPI server — dashboard API and SSE streaming
main.py                  # Bot orchestrator — loops through accounts
account_processor.py     # Per-account flow and execution logic

broker.py                # IBKR connection, price fetching, order placement
rules.py                 # Config-driven rule evaluation
config.py                # Loads settings from config_store.json
config_store.json        # Single source of truth for all settings

allocator_registry.py    # Maps allocator names to functions
allocator_pension.py     # 3-ETF allocation strategy
allocator_joint.py       # 1-ETF allocation strategy
allocator_otto.py        # 1-ETF allocation strategy

pending_topup.py         # Persistent state for incomplete trades

dashboard/
  index.html             # Main dashboard (preview + execute)
  settings.html          # Settings editor

start_dashboard.bat      # Double-click to start the server + open browser
```

The logic is intentionally split:
- **Allocator** → what to buy
- **Rules** → whether to buy
- **Broker** → how to buy

---

## Requirements

### 1. Python 3.10+
[https://www.python.org/](https://www.python.org/)

### 2. Interactive Brokers
- A live and/or paper trading account
- IB Gateway running locally (managed automatically via IBC — see below)
- API access enabled in Gateway settings
- Ports: live `4001`, paper `4002`

### 3. IBC (IB Controller)
Automates Gateway login so you only need to approve a phone MFA prompt.
See **IBC Setup** section below.

### 4. Python dependencies

```bash
pip install -r requirements.txt
```

---

## Starting the Dashboard

Double-click **IBKR ETF Bot** on your desktop (or run `start_dashboard.bat`).

This opens a small terminal window running the server and automatically opens **http://localhost:9000** in your browser.

The server only runs while that terminal window is open. When you close the browser tab, IB Gateway is automatically shut down.

---

## Using the Dashboard

### Dashboard (http://localhost:9000)

**Accounts panel** — shows all configured accounts with their ETFs and target weights.

**Preview all** — runs the bot in preview mode. Shows per-account cards with:
- Available cash
- Allocation rows (ticker, shares, price, total, rounding notes)
- Top-up status messages
- Cash remaining after allocation

**Execute all** — enabled after a successful preview. Requires the Gateway connection indicator (top right) to be green. Places real orders and updates the cards with fill status.

**Raw log toggle** — shows the full bot console output for debugging.

### Settings (http://localhost:9000/settings)

Edit all configuration without touching code:

| Setting | Description |
|---|---|
| Environment | Switch between paper and live trading |
| Execution mode | Whether Execute actually places orders |
| Commission buffer | EUR reserved per order for IBKR commission |
| Max top-up age | Days before a pending top-up file expires |
| IBC script path | Full path to `StartGateway.bat` |
| Per-account: enabled | Whether the bot processes this account |
| Per-account: allocation cap | Optional cash cap (leave blank to use all cash) |
| Per-account: limit order markup | % above last price for limit orders |
| Per-account: min cash | Minimum cash before any orders are placed |
| Per-account: top-up settings | Enable/disable and threshold |
| Per-account: ETF table | Ticker, exchange, currency, target weight % |

Click **Save settings** to write changes to `config_store.json`. Changes take effect on the next run.

---

## Configuration

All settings live in `config_store.json`. This file is read at runtime by the bot and written by the Settings page. You can also edit it directly.

### planned_allocation_cash

An optional cap on how much cash is used for allocation per account. Useful if you only want to invest part of your available balance.

- If set: `usable cash = min(real_cash, planned_allocation_cash)`
- If `null`: uses full available cash
- In execute mode: if `planned_allocation_cash > real_cash`, the bot stops with a safety error

---

## Allocation Strategies

### Pension (3 ETFs)

Splits available cash across 3 ETFs by target weight (e.g. 60/30/10). Applies rounding rules per ETF. If an ETF's fractional part exceeds the `topup_trigger` threshold, a top-up is triggered instead of buying a partial amount.

### Joint / Otto (1 ETF)

Invests 100% of available cash into a single ETF. Same top-up logic applies.

---

## Top-Up System

Avoids placing very small orders when you're close to affording one more share.

### How it works

1. Allocator determines you're close to affording the next share (fractional part ≥ `topup_trigger`)
2. Bot skips the purchase and saves a `pending_topup_{account}.json` file
3. You deposit the suggested top-up amount into that account
4. On the next run, the bot detects the pending file, checks if you're now funded, and executes

### What you see in the dashboard

The summary card shows status messages as the top-up is processed:

| Status | Meaning |
|---|---|
| 🔵 Pending top-up loaded | A pending file was found and loaded |
| 🟠 Pending top-up expired | File was too old and discarded |
| 🟢 Top-up fully funded — order will be placed | Cash is sufficient, order proceeds |
| 🟠 Top-up not yet fully funded | Still not enough cash |
| 🟠 Still missing: EUR X.XX | Exact shortfall shown |
| 🔵 Top-up file saved for next run | New pending file created |
| 🟢 Top-up completed and cleared | Purchase done, file removed |

### Key behaviour

- Pending files are **account-specific** — multiple accounts work independently
- Files **auto-expire** after 7 days (configurable in Settings)
- The suggested deposit amount uses the **limit price** (not raw price) to match actual required cash
- Preview mode never creates or modifies pending files
- The pending file is only saved after all other orders in that run have successfully filled

---

## IBC Setup

IBC (IB Controller) automates IB Gateway login so you only need to approve the MFA prompt on your phone.

### One-time setup

1. Download IBC from [https://github.com/IbcAlpha/IBC/releases](https://github.com/IbcAlpha/IBC/releases) — get the Windows release (`IBCWin_x.x.x.zip`)
2. Extract to a permanent folder (this repo already includes an `IBC/` folder)
3. Edit `IBC/config.ini` and fill in your credentials:
   ```ini
   IbLoginId=YOUR_IBKR_USERNAME
   IbPassword=YOUR_IBKR_PASSWORD
   TradingMode=live
   FIX=no
   ```
4. In the Settings page, set **IBC script path** to the full path of `StartGateway.bat`

### What happens when you click Preview or Execute

If IB Gateway is already running, the bot connects immediately.

If Gateway is not running, the bot starts it via IBC:

```
IB Gateway not running — starting via IBC...
Approve the 2FA prompt on your phone.
  Waiting for Gateway... (1/10)
  Waiting for Gateway... (2/10)
IB: connected
```

Approve the MFA on your IBKR Mobile app. The bot connects automatically once Gateway is ready (retries for ~50 seconds).

The **Gateway indicator** in the dashboard header turns green once the first account connects successfully.

### Gateway shutdown

When you close the browser tab, IB Gateway is automatically shut down. This prevents the daily IBKR nightly restart from triggering another MFA prompt.

Navigating between Dashboard and Settings does not shut down Gateway.

### Security note

Your IBKR credentials live in `IBC/config.ini` — this file is excluded from git via `.gitignore`.

---

## Safety Checks

The bot will refuse to execute if any of the following are true:

| Check | Behaviour |
|---|---|
| Preview mode (no Execute clicked) | No orders placed |
| `execution_mode = "preview"` in config | Orders blocked even if Execute clicked |
| Price unavailable | Safety stop — account skipped |
| Contract cannot be qualified | Safety stop — account skipped |
| Market closed | Blocked — shown in output |
| Cash below `min_cash_to_execute` | Blocked — shown in output |
| `planned_allocation_cash > real_cash` (execute mode) | Safety stop |
| Gateway not connected (green indicator) | Execute button blocked |

---

## Known Limitations

- **No retry for unfilled limit orders** — if a limit order times out (2 min) and remains open at IBKR, the bot warns you and stops. Check TWS before re-running.
- **No file logging** — all output is streamed to the dashboard. The raw log is visible during the session but not persisted.
- **No FX handling** — assumes account currency matches ETF currency.
- **Static commission** — `order_commission_buffer` is a manual setting, not fetched dynamically from IBKR.
- **Localhost only** — the dashboard runs on your laptop. Phone access requires a VPS (easy migration path when needed).

---

## Future Improvements

- Scheduled / automated runs
- Retry mechanism for unfilled limit orders
- Dynamic commission fetched from IBKR
- VPS deployment for remote access
