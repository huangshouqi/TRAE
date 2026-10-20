@echo off
chcp 65001 >nul
setlocal

rem ============================================================
rem 项目备份到飞书云空间（每次更新后双击运行）
rem 作用：把 ladder 项目（daily_ladder.py / run_daily.cmd /
rem       requirements.txt / pylibs / data）重新打包为
rem       ladder_portable_20261020.zip，
rem       并覆盖上传到飞书「连板天梯-ladder」文件夹。
rem 前提：本机已通过 lark-cli 完成飞书授权（auth login）。
rem 依赖：Windows 自带 tar.exe（Win10 1803 及以上）
rem ============================================================

rem 定位项目根目录（本脚本位于 ladder 子目录内）
pushd "%~dp0.."
set "ROOT=%CD%"
popd
set "LADDER=%ROOT%\ladder"

set "ZIPNAME=ladder_portable_20261020.zip"
set "ZIP=%ROOT%\%ZIPNAME%"

set "LARK=C:\Users\Archie\.trae-cn\plugins\trae-remote-official\lark\1.0.5\bin\lark-cli.exe"
set "FOLDER_TOKEN=Ov4Hf6Xupl4xkrdnrHYcgMjznXd"
set "FILE_TOKEN=GxkdbfLHYo0n7kxG7wYcSoWQnXd"

set "AUTHOUT=%TEMP%\lark_auth_status.txt"
set "UPLOADOUT=%TEMP%\lark_upload_result.json"

if not exist "%LARK%" (
  echo [错误] 未找到 lark-cli：
  echo   %LARK%
  echo 请确认飞书插件已安装后再试。
  goto :fail
)
if not exist "%LADDER%\daily_ladder.py" (
  echo [错误] 未在当前目录找到 daily_ladder.py，请把本脚本放在 ladder 目录内运行。
  goto :fail
)

echo [1/3] 检查飞书登录状态 ...
"%LARK%" auth status > "%AUTHOUT%" 2>&1
findstr /C:"tokenStatus" "%AUTHOUT%" | findstr /C:"valid" >nul
if errorlevel 1 (
  echo.
  echo [错误] 飞书登录已失效或未授权，请先重新授权：
  echo   "%LARK%" auth login
  echo 授权成功后再双击本脚本。
  goto :fail
)

echo [2/3] 重新打包项目 ...
if exist "%ZIP%" del /q "%ZIP%"
tar.exe -a -cf "%ZIP%" -C "%LADDER%" daily_ladder.py run_daily.cmd backup_to_feishu.cmd requirements.txt pylibs data
if errorlevel 1 (
  echo [错误] 打包失败。
  goto :fail
)
echo   已生成：%ZIP%

echo [3/3] 覆盖上传到飞书（连板天梯-ladder）...
pushd "%ROOT%"
"%LARK%" drive +upload --file "%ZIPNAME%" --folder-token "%FOLDER_TOKEN%" --file-token "%FILE_TOKEN%" --as user > "%UPLOADOUT%" 2>&1
set "RC=%ERRORLEVEL%"
popd

if not "%RC%"=="0" (
  echo [错误] 上传失败，接口返回：
  type "%UPLOADOUT%"
  goto :fail
)
findstr /R /C:"ok.*true" "%UPLOADOUT%" >nul
if errorlevel 1 (
  echo [错误] 上传未成功，接口返回：
  type "%UPLOADOUT%"
  goto :fail
)

echo.
echo [完成] 已备份到飞书云空间（覆盖更新）：
echo   文件夹：连板天梯-ladder
echo   文件  ：%ZIPNAME%
echo   链接  ：https://my.feishu.cn/file/%FILE_TOKEN%
goto :done

:fail
echo.
echo 备份未完成。

:done
pause
endlocal
