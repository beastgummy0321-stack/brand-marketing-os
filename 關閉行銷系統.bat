@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal enabledelayedexpansion

rem One-click killer: stop whatever is listening on port 8710 (the marketing OS server).
set FOUND=0
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":8710 .*LISTENING"') do (
    echo 找到正在跑的行銷系統（代號 %%p），關閉中...
    taskkill /PID %%p /T /F >nul 2>&1
    set FOUND=1
)

echo.
if "!FOUND!"=="0" (
    echo 目前沒有在跑的行銷系統，不用關。
) else (
    echo 已經關掉了。要重新開，點兩下「啟動行銷系統.bat」。
)
echo.
echo 按任意鍵關閉這個視窗。
pause >nul
