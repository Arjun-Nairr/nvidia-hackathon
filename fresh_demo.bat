@echo off
rem Starts a FRESH demo: asks once, archives and clears the current demo progress (the same reset as Restart demo in the app), then starts the app like run.bat.
rem Keeps API keys, the project login, catalogue/photos, model settings, paid-call counters and this window's ECOM_* settings. Open http://127.0.0.1:8800
rem If the app is already running, the restart goes through it instead and no second app is started. To continue the current demo, use run.bat.
set PY=%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe
cd /d "%~dp0"
"%PY%" scripts\fresh_demo.py %*
if errorlevel 2 exit /b 0
if errorlevel 1 exit /b 1
"%PY%" scripts\setup.py >nul && "%PY%" -m app.server
