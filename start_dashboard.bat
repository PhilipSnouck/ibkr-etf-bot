@echo off
cd /d "%~dp0"
start "IBKR ETF Bot" cmd /k uvicorn server:app --port 9000
timeout /t 2 /nobreak >nul
start "" http://localhost:9000
