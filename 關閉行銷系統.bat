@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal enabledelayedexpansion

rem 一鍵關閉：關掉佔用 8710 埠的行銷系統，連同它那個黑視窗一起收掉。
set FOUND=0
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":8710 .*LISTENING"') do (
    echo 找到正在跑的行銷系統（代號 %%p），關閉中...
    taskkill /PID %%p /T /F >nul 2>&1
    set FOUND=1
)

rem 伺服器是用 cmd /k 開的，殺掉 python 之後那個黑視窗還會留著、看起來像沒關成功，
rem 一併收掉。找不到就算了（使用者可能是用開機自動啟動那條路開的，沒有這個視窗）。
taskkill /FI "WINDOWTITLE eq Marketing OS Server*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Marketing OS Worker*" /T /F >nul 2>&1

echo.
if "!FOUND!"=="0" (
    echo 目前沒有在跑的行銷系統，不用關。
) else (
    echo 已經關掉了。要重新開，點兩下「啟動行銷系統.bat」。
)
echo.
echo 按任意鍵關閉這個視窗。
pause >nul
