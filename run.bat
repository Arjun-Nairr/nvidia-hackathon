@echo off
rem Starts the app with Hermes' own Python. Open http://127.0.0.1:8800
set PY=%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe
cd /d "%~dp0"
"%PY%" scripts\setup.py >nul && "%PY%" -m app.server
