@echo off
rem Lint the project (run it as .\lint.bat; a bare lint.bat is not found when NoDefaultCurrentDirectoryInExePath is set, as on this PC): Ruff (Python in app\, scripts\, tests\) and ESLint (frontend, including inline <script> blocks in app\static\*.html).
rem   .\lint.bat         run both checks; exit code 0 only when both pass, 1 when a check reports findings, 2 when tooling is missing
rem   .\lint.bat setup   one-time: create the project-local .venv-lint (pinned Ruff) and install the pinned ESLint packages (npm ci)
rem Development tooling only: it never touches the Hermes environment, runtime\ or the application's startup.
setlocal
cd /d "%~dp0"
set "RUFF=.venv-lint\Scripts\ruff.exe"
set "ESLINT=node_modules\.bin\eslint.cmd"

if /i "%~1"=="setup" goto :setup

if not exist "%RUFF%" (
  echo [lint] Ruff is not installed. Run:  .\lint.bat setup
  exit /b 2
)
if not exist "%ESLINT%" (
  echo [lint] ESLint is not installed. Run:  .\lint.bat setup
  exit /b 2
)

set FAIL=0
echo [lint] Ruff: app scripts tests
"%RUFF%" check app scripts tests
if errorlevel 1 set FAIL=1

echo [lint] ESLint: app\static ^(inline scripts in HTML and .js files^)
call "%ESLINT%" --max-warnings 0 app/static
if errorlevel 1 set FAIL=1

if "%FAIL%"=="1" (
  echo [lint] FAILED: fix the findings above.
  exit /b 1
)
echo [lint] OK: Ruff and ESLint passed.
exit /b 0

:setup
where node >nul 2>nul
if errorlevel 1 (
  echo [lint] Node.js was not found on PATH. Install Node.js 20.19+/22.13+/24+ and run .\lint.bat setup again.
  exit /b 2
)
set "PYLAUNCH="
where py >nul 2>nul && set "PYLAUNCH=py -3"
if not defined PYLAUNCH where python >nul 2>nul && set "PYLAUNCH=python"
if not defined PYLAUNCH (
  echo [lint] No Python found on PATH ^(py or python^). Install Python 3.9+ and run .\lint.bat setup again.
  exit /b 2
)
if not exist "%RUFF%" (
  echo [lint] Creating .venv-lint
  %PYLAUNCH% -m venv .venv-lint || exit /b 2
)
.venv-lint\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements-lint.txt || exit /b 2
call npm ci --no-audit --no-fund --ignore-scripts || exit /b 2
echo [lint] Setup done. Run: .\lint.bat
exit /b 0
