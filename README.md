# IBKR Multi-Account ETF Bot

## Overview

This project is a **Python-based investment bot** that automates periodic ETF/stock purchases via **Interactive Brokers (IBKR)**.

It is designed to:

* Be run manually once per period
* Use config-driven allocation strategies based on:
  * available funds per account
  * asset prices
  * target allocation percentages
* Prevent inefficient trades using a smart top-up system
* Execute orders when explicitly confirmed
* Be safe by default (no accidental execution)

---

## What This Bot Does

For each configured account, the bot:

1. Connects to IBKR
2. Reads available cash
3. Fetches ETF/stock prices
4. Calculates how many shares to buy
5. Applies safety rules
6. Either:

   * Shows a **preview** (default), or
   * Executes trades (only with explicit confirmation)

The logic is split cleanly between:

* **Allocator** → what to buy
* **Rules** → whether to buy
* **Broker** → how to buy

---

## Key Features

* Multi-account support
* Paper vs live trading
* Preview mode (safe default)
* Explicit execution (`buy` flag required)
* Allocation strategies (1 ETF / 3 ETF)
* Smart **top-up system**
* Market hours validation
* Automatic pending order handling
* Clear console output

---

## Tools & Requirements

To run this project, you need:

### 1. Python

* Version: **3.10+**
* Install: [https://www.python.org/](https://www.python.org/)

### 2. Visual Studio Code (recommended)

* Download: [https://code.visualstudio.com/](https://code.visualstudio.com/)
* Useful for editing and running the bot

### 3. Git & GitHub

* Git: [https://git-scm.com/](https://git-scm.com/)
* GitHub account: [https://github.com/](https://github.com/)

Used for:

* Version control
* Sharing the project
* Backup

### 4. Interactive Brokers (IBKR)

* Account (paper + live)
* IB Gateway **or** Trader Workstation (TWS)

Enable:

* API access
* Correct ports (see config)

### 5. Python dependencies

Install with:

```bash
pip install -r requirements.txt
```

---

## Project Structure

```text
main.py                  # Main orchestrator
account_processor.py     # Per-account logic (core flow)

broker.py                # IBKR connection & trading
rules.py                 # Config-driven rules
config.py                # All settings

allocator_registry.py    # Allocator mapping
allocator_pension.py     # 3-ETF strategy
allocator_joint.py       # 1-ETF strategy
allocator_otto.py        # 1-ETF strategy

pending_topup.py         # Top-up persistence system
```

The system is intentionally modular:

* Easy to extend
* Easy to debug
* Easy to reason about

---

## Configuration

All configuration lives in:

```python
config.py
```

### Environment

```python
IB_ENVIRONMENT = "paper"  # or "live"
```

* `paper` → safe testing
* `live` → real money

---

### Execution Mode

```python
EXECUTION_MODE = "execute"
```

* `"preview"` → never places orders
* `"execute"` → allows orders (only with `buy` flag)

---

### Accounts

Each account is fully configurable:

```python
ACCOUNTS = {
    "Pension": {
        "enabled": True,
        "allocator": "pension",
        ...
    }
}
```
Planned Allocation Cash (Important)
The bot supports an optional per-account setting:
"planned_allocation_cash": 2100
This controls how much cash is used for the allocation decision, without modifying the actual account balance.

Behavior
For each run:
* The bot always reads real IBKR cash
* If planned_allocation_cash is set:

the bot uses:usable_cash = min(real_cash, planned_allocation_cash)
If planned_allocation_cash = None: the bot uses full available cash

Example
* Real cash: EUR 8,000
* Planned allocation cash: EUR 2,100
* Usable cash for this run: EUR 2,100

This allows you to:

allocate only part of your account to this strategy
simulate different allocation sizes before executing trades

Each account defines:

* IBKR account ID
* Currency
* Allocation strategy
* Rules (min cash, top-up behavior)
* ETF list

---

## Allocation Logic

### Pension (3 ETFs)

* Splits cash across 3 ETFs
* Applies rounding rules
* Uses leftover cash for ETF3
* Can trigger top-up instead of buying partial ETF3 

---

### Joint / Otto (1 ETF)

* Invests 100% into a single ETF
* If close to next share → triggers top-up instead of partial buy  

---

## Top-Up System (Important)

The bot avoids inefficient small trades.

### How it works

If there is not enough cash to buy a “meaningful” amount:

1. Bot **does NOT buy**
2. Creates a **pending_topup JSON file**
3. Waits for you to add funds
4. On next run:

   * Executes the trade
   * Deletes the file automatically 

---

### Key Behavior

* Top-ups are **account-specific**
* Files auto-expire after a few days
* Preview mode **never creates files**

---

## How to Run

### 1. Preview Mode (Always do this first)

```bash
python main.py
```

* No trades executed
* Shows full plan
* Shows if top-up is needed

---

### 2. Execute Trades

```bash
python main.py buy
```

Orders will only execute if:

* `EXECUTION_MODE = "execute"`
* `buy` argument is provided
* All safety checks pass 

---

## Safety System (Very Important)

This bot is designed to **protect you from mistakes**, but you must still use it correctly.

### Built-in safeguards

* No execution without `buy` flag
* Preview mode by default
* Market-hours checks
* Invalid price detection
* Min cash rules
* Top-up blocking logic
* Live mode protection (no test cash allowed) 

---

### Rules you MUST follow

1. Always run preview first
2. Verify:

   * Cash
   * Prices
   * Share counts
3. Only then run:

   ```bash
   python main.py buy
   ```
4. Start in **paper mode**
5. Only switch to **live** when fully confident

---

## Example Flows

### Normal execution

1. Run preview
2. Check output
3. Run `buy`
4. Orders executed

---

### Top-up scenario

1. Run preview → insufficient funds
2. Run `buy` → creates pending file
3. Add funds
4. Run `buy` again → executes

---

## How It Works Internally (High Level)

1. `main.py` loops through accounts 
2. `account_processor.py` handles per-account flow 
3. Allocator decides **what to buy**
4. Rules decide **if allowed** 
5. Broker executes via IBKR 
6. Pending system handles incomplete trades

---

## Final Notes

This bot is:

* Deterministic
* Transparent
* Safe by design

But it still interacts with **real money**.

> Always double-check before executing trades.

---

## Future Improvements (Optional)

* Scheduling (cron / automation)
* Logging to file
* Notifications (email / Telegram)
* UI dashboard

