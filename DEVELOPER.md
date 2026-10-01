# Developer Documentation - IBKR ETF Bot

Technical context for a developer or LLM working on this codebase.
Usage instructions live in `README.md`; tasks in `ROADMAP.md`.

> **This bot places real-money orders on live Interactive Brokers accounts.**
> Never change order or broker logic unless Philip explicitly asks. Keep the
> Preview → Execute safety model intact. Never open `.env`, `config_store.json`,
> `pending_topup*.json`, or anything in `../IBC` - real account data and credentials.

---

## Repo & location

- **GitHub:** https://github.com/PhilipSnouck/ibkr-etf-bot (private)
- **Local:** `C:\Users\p.snouckaert\Personal repos\IBKR-bot-docs\IBKR-etf-bot`
- **Runs:** localhost only, on Philip's laptop. No deploy pipeline.

**Folder quirk (intentional - never "fix"):** the git repo is this `IBKR-etf-bot`
folder, nested inside the plain (non-git) parent folder `IBKR-bot-docs`. The parent
also holds `IBC/` (IB Gateway login config, contains credentials, never open) and
`dashboard-mockup/` (design scratchpad). Neither is part of the repo.

---

## Stack

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.10+ | Plain scripts, no package structure |
| Server | FastAPI + uvicorn | `server.py`, serves dashboard + SSE |
| IBKR API | `ib_async` | The maintained fork of ib_insync - `broker.py` imports `ib_async`, not `ib_insync` (docs elsewhere may say ib_insync) |
| Gateway login | IBC (IB Controller) | `StartGateway.bat` in `../IBC`, auto-started by `broker.connect_ib()` |
| Frontend | Vanilla HTML/JS, no build step | `dashboard/index.html` + `settings.html`, talk to the API via `fetch` + `EventSource` |
| Config | `config_store.json` (gitignored) | Single source of truth, edited via Settings page |

Ports: live Gateway `4001` (clientId 2), paper `4002` (clientId 1) - hardcoded in `config.py` `IB_CONNECTIONS`.

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
IBKR_dashboard.bat     cd to repo, start `python -m uvicorn server:app --port 9000`, open http://localhost:9000
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
      execution_result, error, mfa_prompt, done - plus every raw line as {type:"raw"}
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
  `GET /api/run/{preview|execute}` (SSE), `POST /api/shutdown` (taskkills IBGateway.exe  - 
  fired by `navigator.sendBeacon` on tab close so the nightly Gateway restart can't trigger a stray MFA).

---

## Configuration

All runtime settings live in `config_store.json` (gitignored - **never open it**, it holds
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
  to a valid tick with Decimal arithmetic (`round_up_to_tick`), which avoids IBKR Error 110
  ("price does not conform to the minimum price variation").
- **Tick size comes from the market rule of the venue the order is routed to**, not from
  `minTick` and not from the listing exchange. `get_price_increment` reads the contract's
  market rule (`reqMarketRule`) and returns the increment for the band the price falls in.
  Two traps, both real and both already hit:
  1. `minTick` is only the *smallest possible* tick; MiFID II venues widen the tick as the
     price rises, so a minTick-conforming price can still be rejected.
  2. The listing exchange and SMART can have **different rules for the same contract**.
     IMAE reports a flat 0.005 tick on AEB but a banded rule on SMART where EUR 100-200
     requires 0.02, so EUR 105.83 passed the bot's check and was cancelled by IBKR
     (2026-09-01). Since orders always go to SMART, SMART's rule is the one that counts.
  Falls back to `minTick`, then to 0.01, if the rule cannot be read, so it can never be
  worse than no lookup at all. Guarded by `test_tick_conformance.py`.
- **SMART routing**: `place_order` copies the contract, sets `primaryExchange` to the listing
  exchange and `exchange = "SMART"`, which avoids Error 10311 from Gateway precautionary
  settings (which reset on every Gateway restart).
- **Guards in place_order**: quantity > 0 and limit_price > 0 or ValueError.
- **Order routing**: `build_routing_contract` sends `conId` + `exchange="SMART"` + currency and
  nothing else. SMART is a routing destination, not an instrument chooser, and `conId` is
  IBKR's unique key. Copying the qualified contract and swapping only the exchange used to
  carry `localSymbol` and `tradingClass` from the listing venue, which IBKR rejected with
  Error 478. The routed contract is re-qualified and the order is refused unless conId,
  symbol and currency all match the contract that was priced.
- **Pre-flight** (`_preflight_account`): an account's legs are placed together, so a leg that
  fails at placement time would leave the account off its target weights. `prepare_order`
  resolves and checks every leg without sending it, and `execute_plan` places **nothing** for
  an account where any leg fails. It catches an unresolvable routing contract, a
  non-conforming price, a plan whose total cost **at the final tick-snapped prices** exceeds
  real cash (the sizing in `main.py` uses the unsnapped price, so the snap can add cents per
  share it never saw), and an unreadable cash balance. A failed pre-flight skips that account
  only; the others still run. `server.py` parses the failure line so the dashboard cannot
  leave a stale "Ready" badge on an account that bought nothing.
  A leg rejected **after** placement still leaves a partial. Sequential placement with
  stop-on-failure was declined (see ROADMAP): it costs up to two minutes per leg and lets the
  price drift between them.
- **Safety stops** (account skipped, nothing placed): cash unreadable, contract won't
  qualify, price missing/≤ 0, `planned_allocation_cash > real_cash` in execute mode,
  cash below `min_cash_to_execute`, market closed for any ETF with shares > 0.
- **Fill wait**: after pre-flight passes and all orders for an account are placed simultaneously, `execute_plan`
  polls up to 120 s for terminal statuses (`Filled/Cancelled/ApiCancelled/Inactive`).
  On timeout it **warns and stops - it does not cancel** the open order. A timed-out DAY
  order can still fill later at IBKR. Always check TWS before re-running execute.
- **Top-up files**: `pending_topup_{account}.json` is saved/cleared only when all orders
  in that run filled; preview never touches these files. Files expire after
  `max_pending_topup_age_days`.
- Prices come from **delayed data** (`reqMarketDataType(3)`), warm-up pass + real pass.
  The markup buffer is what makes delayed-price limits fill anyway.

### Price fallback chain (`get_etf_prices`)

IBKR refuses individual contracts with Error 354 intermittently, and a refusal is
immediate, so retrying the same request changes nothing. Each rung is therefore a
**different request path**, tried only for symbols still missing a price:

1. delayed streaming on the listing venue (warm-up pass, then real pass)
2. delayed streaming routed via **SMART** (orders already route this way; price requests
   did not, and a venue feed can be refused where the SMART composite is served)
3. **delayed frozen** (`reqMarketDataType(4)`), the last known quote
4. last daily close from `reqHistoricalData`, `TRADES` then `MIDPOINT` (a separate service
   at IBKR with its own entitlements)

Only if all four fail is the account skipped. A healthy run never touches rungs 2 to 4, so
this costs nothing when things work. The session is always put back to delayed after the
frozen rung, or later requests would silently keep serving frozen data.

**Why a stale fallback price is safe**: orders are LIMIT orders priced off this number. A
stale-high price puts the limit above the market and fills at the market price; a stale-low
price puts the limit below the market and simply does not fill. The downside of an old
price is a missed fill, never an overpay. Sizing is slightly off, which the commission
buffer and the top-up trigger absorb.

Every rung used is printed, and `Prices:` names the path each price came from, so a fill
can always be traced to the kind of quote behind it. `test_price_fallback.py` covers all
three shapes offline.

### Price diagnostics (`price_diagnostics.py`)

Observation only. It never changes which price the bot uses and never rescues a failed
fetch. It exists because "no valid market price available for VUAA" is unfalsifiable on its
own, and debugging it repeatedly cost whole sessions.

- A single `DIAG` collector is attached to `ib.errorEvent` inside `connect_ib`, **before**
  `reqMarketDataType` and before any settling sleep. The market data farm messages
  (2104 / 2106 / 2158) land in exactly that window and are the thing worth capturing.
- Every fetch prints one summary line showing, per symbol, the price, the data type
  actually received (live / frozen / delayed / delayed-frozen) and which field it came
  from (`marketPrice`, `last`, or the bid/ask midpoint). Successful runs record this too,
  so a later regression can be diagnosed by comparison.
- Every failure prints a full `PRICE DIAGNOSTIC` block: contract, local time, market hours
  (looked up on failure only), connection parameters including **clientId and run mode**,
  per-pass ticker fields, the IBKR messages for that contract, farm status, and a
  plain-language explanation of each code seen.
- **Message ordering uses a sequence counter, not timestamps.** Several messages routinely
  share a millisecond, and the question "did the farm report OK *before* we asked for
  prices" has to be answerable exactly. That comparison is what separates "Gateway's data
  session was not ready" from "the account is not entitled to this venue", which both
  surface as Error 354 and are otherwise indistinguishable.
- `clientId` and run mode are in the report because preview and execute are **separate
  processes that reconnect on the same clientId** (`config.py` → `IB_CONNECTIONS`), which
  is a live suspect for execute-only price failures.

---

## Running it

1. Double-click the **IBKR ETF Bot** desktop shortcut (or `IBKR_dashboard.bat`):
   starts `python -m uvicorn server:app --port 9000` in a cmd window and opens http://localhost:9000.
2. Click **Preview all** - if Gateway isn't running, IBC starts it; approve MFA on phone
   (connect retries ~10 × 5 s, plus 15 s market-data warm-up after a fresh start).
3. Click **Execute all** (only enabled after a clean preview + green Gateway indicator).
4. Close the tab → beacon to `/api/shutdown` kills IBGateway.exe.

Server lives only while the cmd window is open. No linter, no CI. One test:
`python test_tick_conformance.py` (offline, no Gateway, places nothing) checks that every
configured ETF's limit price conforms to the tick IBKR enforces on SMART.

---

## Gotchas

- **`main.py` has no `if __name__ == "__main__"` guard.** It is a top-level script: merely
  `import main` runs a full bot pass, and if Gateway is down that fires IBC's
  `StartGateway.bat` and a 2FA prompt on Philip's phone. Buying still needs `buy` on the
  command line, so an accidental import cannot place orders, but do not import `main` to
  test that the code parses. Use `python -c "import broker"` or `python -m py_compile main.py`.
- Deps are installed **globally** (no venv): `fastapi`, `uvicorn`, `ib_async`, pinned in `requirements.txt`. A Python upgrade or reinstall wipes them; the symptom is the launcher window flashing `No module named uvicorn` and the browser showing `ERR_CONNECTION_REFUSED`. Recover with `python -m pip install -r requirements.txt`. The launcher calls `python -m uvicorn` (not bare `uvicorn`) so it still works when Python's Scripts dir is not on PATH.
- There is **no double-run guard**: re-running Execute after a timeout can double-buy if
  the earlier order is still open (open orders don't reduce reported cash). The planned
  retry feature in ROADMAP.md must confirm cancellation before re-placing.
- `config.py` loads at import time - fine for the bot (fresh subprocess per run), but any
  long-lived import of `config` won't see Settings changes.
- The pension allocator assumes exactly 3 ETFs and that the dict order in config is
  ETF1/ETF2/ETF3 (ETF3 is the remainder/top-up leg). Joint/otto assume exactly 1.
- Dashboard "execute" still does nothing if `execution_mode` is `"preview"` in config  - 
  that's a feature (kill switch), not a bug.
- `__pycache__/` contains stale compiled modules (e.g. an old `allocator.py`) - ignore it.
