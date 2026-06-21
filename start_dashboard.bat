@echo off
cd /d "%~dp0"
start "IBKR ETF Bot" cmd /k uvicorn server:app
timeout /t 2 /nobreak >nul
start "" http://localhost:8000
