@echo off
REM Use this file's own folder; but if it was copied somewhere without server.py
REM (e.g. onto the Desktop), fall back to the real install path so it still works.
set "BOTDIR=%~dp0"
if not exist "%BOTDIR%server.py" set "BOTDIR=C:\Users\p.snouckaert\Personal repos\IBKR-bot-docs\IBKR-etf-bot\"
cd /d "%BOTDIR%"
start "IBKR ETF Bot" cmd /k python -m uvicorn server:app --port 9000
timeout /t 4 /nobreak >nul
start "" http://localhost:9000
