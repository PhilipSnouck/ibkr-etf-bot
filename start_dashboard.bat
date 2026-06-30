@echo off
cd /d "%~dp0"
start "IBKR ETF Bot" cmd /k python -m uvicorn server:app --port 9000
timeout /t 4 /nobreak >nul
start "" http://localhost:9000
