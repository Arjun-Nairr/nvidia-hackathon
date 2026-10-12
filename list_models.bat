@echo off
rem Lists the ChatGPT/Codex models your signed-in subscription offers (live, from your account).
set PY=%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe
cd /d "%~dp0"
"%PY%" scripts\list_models.py
