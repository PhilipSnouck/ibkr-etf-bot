# IBKR ETF Bot

Personal Python bot that automates periodic ETF purchases across Philip's Interactive Brokers
accounts, run manually via a local web dashboard: Preview → Execute.

**Run:** double-click `start_dashboard.bat` (or the "IBKR ETF Bot" desktop shortcut) → opens
http://localhost:8000. Requires IB Gateway (auto-started via IBC) + phone MFA approval.

## Hard rules

- **NEVER open `.env`, `config_store.json`, `pending_topup*.json`, or anything in `../IBC`** —
  they hold real account data and credentials. Document config key names from code only.
- **This bot places REAL money orders.** Never change order/broker/allocator logic unless
  Philip explicitly asks, and keep the Preview-before-Execute safety model intact.

## Pointers
- `README.md` — usage · `DEVELOPER.md` — architecture and internals
- `ROADMAP.md` — tasks. Format spec: `C:\Users\p.snouckaert\Own AI projects\roadmap-dashboard\ROADMAP_TEMPLATE.md`. Always `git pull` before editing it.
