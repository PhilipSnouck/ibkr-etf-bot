# IBKR Multi-Account ETF Bot

## Overview

A Python bot that automates periodic ETF purchases across multiple Interactive Brokers (IBKR) accounts. You run it manually once per period — it calculates how many shares to buy based on available cash and target allocations, then places orders when you explicitly confirm.

Designed to be:
- **Safe by default** — preview mode unless you pass `buy`
- **Deterministic** — same inputs always produce the same plan
- **Transparent** — clear console output at every step

---

## How It Works

For each configured account, the bot:

1. Connects to IBKR
2. Reads available cash
3. Fetches current ETF prices
4. Runs the allocator → calculates how many shares to buy
5. Checks market hours and safety rules
6. Shows a preview
7. If you passed `buy`: places orders

### Order execution

All orders are **limit orders** placed at `price × (1 + markup)` (default: 0.5% above last price). This means:
- You pay at or below the limit price — never above it
- The markup gives a small buffer so the order fills even if the price ticks up slightly between the price fetch and order placement
- Orders are placed simultaneously across all ETFs in an account
- The bot waits up to 2 minutes for fills; if an order hasn't confirmed by then, it prints a warning and stops — check TWS before re-running

### Code structure

```
main.py                  # Orchestrator — loops through accounts
account_processor.py     # Per-account flow and execution logic

broker.py                # IBKR connection, price fetching, order placement
rules.py                 # Config-driven rule evaluation
config.py                # All settings live here

allocator_registry.py    # Maps allocator names to functions
allocator_pension.py     # 3-ETF allocation strategy
allocator_joint.py       # 1-ETF allocation strategy
allocator_otto.py        # 1-ETF allocation strategy

pending_topup.py         # Persistent state for incomplete trades
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
- IB Gateway **or** Trader Workstation (TWS) running locally
- API access enabled in TWS/Gateway settings
- Correct ports configured (see `config.py`)

### 3. Python dependencies

```bash
pip install -r requirements.txt
```

---

## Configuration

Everything lives in `config.py`. You should not need to touch any other file for normal configuration.

### Environment

```python
IB_ENVIRONMENT = "paper"  # or "live"
```

Switches between paper trading (port 4002) and live trading (port 4001).

### Execution mode

```python
EXECUTION_MODE = "execute"
```

- `"preview"` — never places orders, regardless of arguments
- `"execute"` — allows orders, but only when `buy` argument is also passed

### Order settings

```python
ORDER_COMMISSION_BUFFER = 1.25   # EUR reserved per order for IBKR commission
DEFAULT_LIMIT_ORDER_MARKUP = 0.005  # 0.5% above last price
```

### Accounts

Each account is independently configured:

```python
ACCOUNTS = {
    "Pension": {
        "enabled": True,
        "account_ids": {
            "paper": "DUxxxxxx",
            "live":  "Uxxxxxxx",
        },
        "currency": "EUR",
        "allocator": "pension",
        "limit_order_markup": 0.005,
        "planned_allocation_cash": None,
        "rules": {
            "min_cash_to_execute": 0,
            "pending_topup_enabled": True,
            "topup_trigger": 0.75,
        },
        "etfs": {
            "VUAA": { "exchange": "BVME.ETF", "currency": "EUR", "target_weight": 0.60, ... },
            ...
        },
    },
}
```

Key settings per account:

| Setting | Description |
|---|---|
| `enabled` | Whether the bot processes this account |
| `account_ids` | IBKR account ID per environment |
| `allocator` | Which allocation strategy to use |
| `limit_order_markup` | How far above last price to set the limit (e.g. `0.005` = 0.5%) |
| `planned_allocation_cash` | Optional cash cap (see below) |
| `min_cash_to_execute` | Minimum cash before any orders are placed |
| `pending_topup_enabled` | Whether to use the top-up system for this account |
| `topup_trigger` | Fractional share threshold that triggers a top-up (e.g. `0.75`) |

### planned_allocation_cash

An optional cap on how much cash is used for allocation. Useful if you only want to invest part of your available balance.

```python
"planned_allocation_cash": 2100  # only allocate up to EUR 2,100
```

- If set: `usable cash = min(real_cash, planned_allocation_cash)`
- If `None`: uses full available cash
- In execute mode: if `planned_allocation_cash > real_cash`, the bot stops with a safety error

---

## Allocation Strategies

### Pension (3 ETFs)

Splits available cash across 3 ETFs by target weight (e.g. 60/30/10). Applies rounding rules per ETF and uses the remainder for ETF3. If ETF3's fractional part exceeds the `topup_trigger` threshold, a top-up is triggered instead of buying a partial amount.

### Joint / Otto (1 ETF)

Invests 100% of available cash into a single ETF. Same top-up logic applies.

---

## Top-Up System

Avoids placing very small orders when you're close to being able to afford one more share.

### How it works

1. Allocator determines you're close to affording the next share (fractional part ≥ `topup_trigger`)
2. Bot skips the purchase and saves a `pending_topup_{account}.json` file
3. You deposit the suggested amount
4. On the next run, the bot detects the pending file, checks if you're now funded, and executes

### Key behaviour

- Pending files are **account-specific** — multiple accounts work independently
- Files **auto-expire** after 7 days (configurable via `MAX_PENDING_TOPUP_AGE_DAYS`)
- The suggested deposit amount uses the **limit price** (not raw price) to match the actual required cash
- Preview mode never creates or modifies pending files
- The pending file is only saved after all other orders in that run have successfully filled

---

## Running the Bot

### Step 1 — Preview (always do this first)

```bash
python main.py
```

Shows the full plan: prices, share counts, allocation percentages, cash remaining. No orders placed.

### Step 2 — Execute

```bash
python main.py buy
```

Places orders only if:
- `EXECUTION_MODE = "execute"` in `config.py`
- `buy` argument is passed
- All safety checks pass (market open, sufficient cash, valid prices)

---

## Safety Checks

The bot will refuse to execute if any of the following are true:

| Check | Behaviour |
|---|---|
| No `buy` argument | Preview only |
| `EXECUTION_MODE = "preview"` | Preview only |
| Price unavailable | Safety stop — account skipped |
| Contract cannot be qualified | Safety stop — account skipped |
| Market closed | Blocked — shown in output |
| Cash below `min_cash_to_execute` | Blocked — shown in output |
| `planned_allocation_cash > real_cash` (execute mode) | Safety stop |

---

## Example Flows

### Normal run

```
python main.py       → check the preview
python main.py buy   → execute
```

### Top-up scenario

```
python main.py buy   → pending file created (e.g. EGLN not bought)
                     → deposit suggested amount
python main.py buy   → pending order executed, file deleted
```

### Switching environments

Change one line in `config.py`:
```python
IB_ENVIRONMENT = "live"  # was "paper"
```

---

## Automating IB Gateway Startup

By default you need to open IB Gateway manually before running the bot. You can
automate this using **IBC** (IB Controller), an open-source tool that starts Gateway
and logs in automatically.

### One-time IBC setup

1. Download IBC from [https://github.com/IbcAlpha/IBC/releases](https://github.com/IbcAlpha/IBC/releases)
   — get the Windows release (`IBCWin_x.x.x.zip`)
2. Extract to a permanent folder, e.g. `C:\IBC\`
3. Create `config.ini` in your IBC folder and fill in your credentials:
   ```ini
   IbLoginId=YOUR_IBKR_USERNAME
   IbPassword=YOUR_IBKR_PASSWORD
   TradingMode=live
   FIX=no
   ```
4. In `config.py`, set:
   ```python
   IBC_SCRIPT_PATH = r"C:\IBC\StartGateway.bat"
   ```

### What happens when you run the bot

If IB Gateway is already running, the bot connects immediately as normal.

If Gateway is not running, the bot starts it via IBC and waits:

```
IB Gateway not running — starting via IBC...
Approve the 2FA prompt on your phone.
  Waiting for Gateway... (1/10)
  Waiting for Gateway... (2/10)
IB: connected
```

You approve the 2FA on your phone, and the bot connects automatically once Gateway is ready.
The bot retries for up to ~50 seconds (10 attempts × 5 seconds).

### Security note

Your IBKR credentials live in `config.ini` inside your IBC folder — outside the project folder and never committed to git.

---

## Known Limitations

- **No retry for unfilled limit orders** — if a limit order times out (2 min) and remains open at IBKR, the bot warns you and stops. Check TWS before re-running.
- **No file logging** — all output is console only. If run as a scheduled task, output would be lost.
- **No FX handling** — assumes account currency matches ETF currency.
- **Static commission** — `ORDER_COMMISSION_BUFFER` is hardcoded, not fetched dynamically from IBKR.

---

## Future Improvements

- File logging (needed before any automation)
- Scheduled / automated runs
- Retry mechanism for unfilled limit orders
- Dynamic commission fetched from IBKR
