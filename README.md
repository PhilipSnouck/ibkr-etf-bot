# IBKR ETF Bot

A Python bot for automated monthly ETF allocation using IBKR (via IB Gateway).

It connects to Interactive Brokers, reads available cash for a selected account, calculates how many ETF shares to buy based on configured allocation rules, and handles a smart pending top-up workflow for the third ETF.

## Current status

Implemented and working:

- IBKR connection
- account cash retrieval
- ETF contract qualification
- ETF price fetching
- 3-ETF allocation engine
- smart top-up handling for ETF3
- pending top-up persistence
- pending expiry handling
- market-hours safeguard
- dry-run mode

Not implemented yet:

- live order execution

---

## Project structure

```text
IBKR-etf-bot/
  main.py            # orchestrates the full flow
  broker.py          # IBKR connection, contract lookup, pricing, market-hours checks
  allocator.py       # allocation logic for the 3-ETF portfolio
  config.py          # account settings and tweakable parameters
  pending_topup.py   # persistence and expiry handling for pending ETF3 purchases
  pending_topup.json # created automatically when a top-up is needed
  README.md