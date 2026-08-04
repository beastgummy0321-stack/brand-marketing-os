@echo off
rem One-click launcher: start server (if not running) then open the UI
cd /d "%~dp0"

rem AI 金鑰放在同資料夾的 .env（不進版控）。要換金鑰就直接編輯 .env。
if exist ".env" for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do set "%%a=%%b"

rem Skip starting if port 8710 is already listening
netstat -ano | findstr /r /c:":8710 .*LISTENING" >nul
if errorlevel 1 (
    start "Marketing OS Server" cmd /k python -m uvicorn app.main:app --port 8710
    timeout /t 3 /nobreak >nul
)

start http://localhost:8710/
