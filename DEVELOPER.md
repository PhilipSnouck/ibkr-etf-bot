# Developer Documentation — IBKR ETF Bot

Technical context for a developer or LLM working on this codebase.
Usage instructions live in `README.md`; tasks in `ROADMAP.md`.

> **This bot places real-money orders on live Interactive Brokers accounts.**
> Never change order or broker logic unless Philip explicitly asks. Keep the
> Preview → Execute safety model intact. Never open `.env`, `config_store.json`,
> `pending_topup*.json`, or anything in `../IBC` — real account data and credentials.

---

## Repo & location

- **GitHub:** https://github.com/PhilipSnouck/ibkr-etf-bot (private)
- **Local:** `C:\Users\p.snouckaert\Own AI projects\IBKR-bot-docs\IBKR-etf-bot`
- **Runs:** localhost only, on Philip's laptop. No deploy pipeline.

**Folder quirk (intentional — never "fix"):** the git repo is this `IBKR-etf-bot`
folder, nested inside the plain (non-git) parent folder `IBKR-bot-docs`. The parent
also holds `IBC/` (IB Gateway login config, contains credentials, never open) and
`dashboard-mockup/` (design scratchpad). Neither is part of the repo.

---

## Stack

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.10+ | Plain scripts, no package structure |
| Server | FastAPI + uvicorn | `server.py`, serves dashboard + SSE |
| IBKR API | `ib_async` | The maintained fork of ib_insync — `broker.py` imports `ib_async`, not `ib_insync` (docs elsewhere may say ib_insync) |
| Gateway login | IBC (IB Controller) | `StartGateway.bat` in `../IBC`, auto-started by `broker.connect_ib()` |
| Frontend | Vanilla HTML/JS, no build step | `dashboard/index.html` + `settings.html`, talk to the API via `fetch` + `EventSource` |
| Config | `config_store.json` (gitignored) | Single source of truth, edited via Settings page |

Ports: live Gateway `4001` (clientId 2), paper `4002` (clientId 1) — hardcoded in `config.py` `IB_CONNECTIONS`.

---

## File structure

```
server.py               FastAPI app: pages, config API, /api/run/{mode} SSE, /api/shutdown
main.py                 Bot entry point (run as subprocess). Loops accounts, builds execution queue
account_processor.py    Pending top-up handling, preview printing, execute_plan()
broker.py               connect_ib (IBC auto-start), cash, contract qualify, prices, market hours, place_order
rules.py                Pure config-reading helpers (enabled, min cash, top-up settings)
config.py               Loads config_store.json into module constants at import time
allocator_registry.py   Name → allocator function map ("pension"/"joint"/"otto")
allocator_pension.py    3-ETF weighted allocation with rounding + top-up logic
allocator_joint.py      1-ETF: all cash into one ETF
allocator_otto.py       1-ETF, same as joint
pending_topup.py        Load/save/clear/expire pending_topup_{account}.json files
dashboard/index.html    Main UI: account cards, Preview/Execute buttons, SSE consumer, raw log
dashboard/settings.html UI editor for config_store.json
start_dashboard.bat     cd to repo, start `uvicorn server:app`, open http://localhost:8000
```

---

## Architecture

```
Browser (index.html)
  → GET /api/run/preview  or  /api/run/execute       (SSE)
    → server.py spawns `python main.py [buy]` as a subprocess
      → main.py: connect_ib() → per account: cash → qualify → prices → allocator → rules → preview
      → execute_plan(): place limit orders via broker.place_order → ib_async → IB Gateway (IBC-launched)
    ← server.py reads stdout line by line, regex-parses it (parse_line) into structured
      SSE events: account_start, cash, allocation, summary, topup, topup_info,
      execution_result, error, mfa_prompt, done — plus every raw line as {type:"raw"}
  ← index.html consumes the events and renders per-account cards
```

Key consequence: **the dashboard is a stdout parser.** `server.py:parse_line()` matches
the exact print formats in `main.py` / `account_processor.py` (e.g. `ACCOUNT: <name>`,
`SUMMARY | ...`, the `--- ORDER PREVIEW ---` table). If you change a print statement,
check the corresponding regex or the card silently loses data (raw log still shows everything).

### Preview → Execute flow

- **Preview** runs `main.py` with no args. `BUY_CONFIRMED` is False → execution queue is built but `execute_plan` receives nothing; nothing is placed, no files written.
- **Execute** runs `main.py buy`. Orders are placed only when **all** of these hold:
  `execution_mode == "execute"` in config AND `buy` arg AND per-account cash rule passes
  AND market open AND the browser-side gates (preview completed with exit 0, Gateway
  indicator green, JS confirm dialog).
- Server endpoints: `GET /` and `/settings` (pages), `GET/PUT /api/config`,
  `GET /api/run/{preview|execute}` (SSE), `POST /api/shutdown` (taskkills IBGateway.exe —
  fired by `navigator.sendBeacon` on tab close so the nightly Gateway restart can't trigger a stray MFA).

---

## Configuration

All runtime settings live in `config_store.json` (gitignored — **never open it**, it holds
real account IDs and cash amounts). Read fresh by each bot subprocess via `config.py`
(import-time load) and read/written by the Settings page through `/api/config`.

Top-level keys (names only, from `config.py`): `ib_environment` (paper/live),
`execution_mode` (preview/execute), `ibc_script_path`, `max_pending_topup_age_days`,
`order_commission_buffer`, `default_limit_order_markup`, `accounts`.

Per-account keys (from `main.py`/`rules.py`): `enabled`, `allocator`, `currency`,
`account_ids` (`paper`/`live`), `planned_allocation_cash` (nullable cap),
`limit_order_markup` (optional override), `etfs` (per symbol: `exchange`, `currency`,
`target_weight`, `rounding`), `rules` (`min_cash_to_execute`, `pending_topup_enabled`,
`topup_trigger`).

---

## Order safety mechanisms (broker.py / account_processor.py)

- **Limit orders only**, BUY, TIF=DAY. Limit = `price × (1 + markup)`, then rounded **up**
  to the contract's minTick with Decimal arithmetic (`round_up_to_tick`, avoids IBKR Error 110).
- **SMART routing**: `place_order` copies the contract, sets `primaryExch` to the listing
  exchange and `exchange = "SMART"` — avoids Error 10311 from Gateway precautionary
  settings (which reset on every Gateway restart).
- **Guards in place_order**: quantity > 0 and limit_price > 0 or ValueError.
- **Safety stops** (account skipped, nothing placed): cash unreadable, contract won't
  qualify, price missing/≤ 0, `planned_allocation_cash > real_cash` in execute mode,
  cash below `min_cash_to_execute`, market closed for any ETF with shares > 0.
- **Fill wait**: after placing all orders for an account simultaneously, `execute_plan`
  polls up to 120 s for terminal statuses (`Filled/Cancelled/ApiCancelled/Inactive`).
  On timeout it **warns and stops — it does not cancel** the open order. A timed-out DAY
  order can still fill later at IBKR. Always check TWS before re-running execute.
- **Top-up files**: `pending_topup_{account}.json` is saved/cleared only when all orders
  in that run filled; preview never touches these files. Files expire after
  `max_pending_topup_age_days`.
- Prices come from **delayed data** (`reqMarketDataType(3)`), warm-up pass + real pass.
  The markup buffer is what makes delayed-price limits fill anyway.

---

## Running it

1. Double-click the **IBKR ETF Bot** desktop shortcut (or `start_dashboard.bat`):
   starts `uvicorn server:app` in a cmd window and opens http://localhost:8000.
2. Click **Preview all** — if Gateway isn't running, IBC starts it; approve MFA on phone
   (connect retries ~10 × 5 s, plus 15 s market-data warm-up after a fresh start).
3. Click **Execute all** (only enabled after a clean preview + green Gateway indicator).
4. Close the tab → beacon to `/api/shutdown` kills IBGateway.exe.

Server lives only while the cmd window is open. No tests, no linter, no CI.

---

## Gotchas

- `README.md` says `pip install -r requirements.txt` but **there is no requirements.txt
  in the repo** — deps are installed globally on this laptop (`fastapi`, `uvicorn`, `ib_async`).
- There is **no double-run guard**: re-running Execute after a timeout can double-buy if
  the earlier order is still open (open orders don't reduce reported cash). The planned
  retry feature in ROADMAP.md must confirm cancellation before re-placing.
- `config.py` loads at import time — fine for the bot (fresh subprocess per run), but any
  long-lived import of `config` won't see Settings changes.
- The pension allocator assumes exactly 3 ETFs and that the dict order in config is
  ETF1/ETF2/ETF3 (ETF3 is the remainder/top-up leg). Joint/otto assume exactly 1.
- Dashboard "execute" still does nothing if `execution_mode` is `"preview"` in config —
  that's a feature (kill switch), not a bug.
- `__pycache__/` contains stale compiled modules (e.g. an old `allocator.py`) — ignore it.
