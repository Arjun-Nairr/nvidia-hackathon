@echo off
rem Sign THIS PROJECT into your ChatGPT/Codex subscription. Credentials go only to runtime\hermes_home\auth.json.
rem If asked whether to import an existing Codex CLI login, answer N (sharing it would break one of the two logins).
set PY=%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe
cd /d "%~dp0"
"%PY%" scripts\setup.py >nul
set HERMES_HOME=%~dp0runtime\hermes_home
set SSL_CERT_FILE=%~dp0runtime\ca_bundle.pem
set REQUESTS_CA_BUNDLE=%~dp0runtime\ca_bundle.pem
"%LOCALAPPDATA%\hermes\bin\hermes.exe" auth add openai-codex --type oauth --label project-dev
"%LOCALAPPDATA%\hermes\bin\hermes.exe" auth status openai-codex
