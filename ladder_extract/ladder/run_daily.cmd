@echo off
chcp 65001 >nul
rem ============================================================
rem 每日连板天梯一键生成（收盘后双击运行即可）
rem 输出：output\YYYY-MM-DD_连板天梯_3x4@2x.png（2160x2880）
rem       output\YYYY-MM-DD_连板天梯_9x16@2x.png（2160x3840）
rem       output\YYYY-MM-DD_发布文案.txt 与 output\latest.png
rem 需要本机已安装 64 位 Windows 版 Python 3.12
rem ============================================================
cd /d "%~dp0"

rem 依次探测 Python 3.12：py 启动器 → 常见安装路径 → PATH 中的 python
set "PY="

py -3.12 -c "import sys" >nul 2>nul
if not errorlevel 1 set "PY=py -3.12"

if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe""

if not defined PY if exist "C:\Python312\python.exe" set "PY="C:\Python312\python.exe""

if not defined PY if exist "C:\Program Files\Python312\python.exe" set "PY="C:\Program Files\Python312\python.exe""

if not defined PY (
  python -c "import sys;assert sys.version_info[:2]==(3,12)" >nul 2>nul
  if not errorlevel 1 set "PY=python"
)

if not defined PY (
  echo [错误] 未找到 64 位 Python 3.12，请先安装后重试：
  echo   https://www.python.org/downloads/
  echo 安装时请勾选 Add python.exe to PATH，并选择 3.12 版本。
  pause
  exit /b 1
)

%PY% -X utf8 "%~dp0daily_ladder.py"
if errorlevel 1 (
  echo.
  echo [错误] 出图失败，请查看上方日志。
  pause
  exit /b 1
)
echo.
echo 已完成：图片与发布文案都在 output 目录，正在打开...
start "" "%~dp0output"
pause
