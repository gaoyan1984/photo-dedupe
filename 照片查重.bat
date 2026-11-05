@echo off
title Photo Dedupe Tool
cd /d "%~dp0"

rem Use python from PATH; fall back to "py" launcher
set "PY=python"
where python >nul 2>nul || set "PY=py"

if "%~1"=="" (
  echo ============================================================
  echo   Photo Dedupe - drag a folder onto this file to scan it
  echo   Or run manually:
  echo     %PY% scripts\run_dedupe.py "D:\My Photos"
  echo     %PY% scripts\build_g_report.py
  echo ============================================================
  pause
  goto :eof
)

echo Scanning: %*
"%PY%" -u "%~dp0scripts\run_dedupe.py" %*

echo.
echo Generating preview report...
"%PY%" -u "%~dp0scripts\build_g_report.py"

echo.
echo Done. Open the generated report folder's index.html in your browser.
pause
