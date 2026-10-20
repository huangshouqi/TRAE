@echo off
chcp 65001 >nul
cd /d "%~dp0"
python "src\lhb_main.py" --open %*
if errorlevel 1 (
  echo.
  echo [FAILED] see message above.
  pause
)
