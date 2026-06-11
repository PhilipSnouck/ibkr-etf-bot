@echo off
cd /d "C:\Users\p.snouckaert\Own AI projects\IBKR-bot-docs\IBKR-etf-bot"
start "IBKR ETF Bot" cmd /k uvicorn server:app
timeout /t 2 /nobreak >nul
start "" http://localhost:8000
