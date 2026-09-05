@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem 一鍵啟動：伺服器沒在跑就開起來，等它真的能連上，再開瀏覽器。
rem 用 curl 探連線，不解析 netstat 的文字輸出——那個輸出隨系統語系變動，一直是隱性地雷
rem （同 app/tools/boot_launcher.py 的說明）。
rem 這個檔必須是 CRLF 換行：cmd 讀 LF-only 的批次檔時，if/for 的括號區塊會解析錯亂。

curl -s -o nul --max-time 2 http://127.0.0.1:8710/
if not errorlevel 1 goto open

if not exist ".venv\Scripts\python.exe" goto novenv

echo.
echo 正在啟動行銷系統，請稍候（第一次會久一點）...
rem 一定要用 .venv 裡的 python：系統的 python 沒有裝這個專案的套件（procrastinate 等），
rem 會在啟動當下就掛掉。cmd /k 讓那個視窗留著，出事時看得到錯誤訊息。
start "Marketing OS Server" cmd /k ".venv\Scripts\python.exe" -m uvicorn app.main:app --port 8710
start /min "Marketing OS Worker" cmd /k ".venv\Scripts\python.exe" -m app.worker

set /a WAITED=0
:wait
rem 用 ping 當 1 秒的 sleep：timeout 在沒有互動主控台時會直接報錯。
ping -n 2 127.0.0.1 >nul
curl -s -o nul --max-time 2 http://127.0.0.1:8710/
if not errorlevel 1 goto open
set /a WAITED+=1
if %WAITED% lss 60 goto wait

echo.
echo 等了 60 秒，行銷系統還是沒有起來。
echo 請看標題「Marketing OS Server」那個黑視窗最後幾行字，問題會寫在那裡。
echo 最常見的原因：資料庫沒開。先執行 supabase start 再點一次這支。
echo.
pause
exit /b 1

:novenv
echo.
echo 找不到 .venv 資料夾，代表套件還沒安裝。
echo 請在這個資料夾按右鍵開啟終端機，執行這一行：
echo     uv sync --frozen
echo 裝完再點一次這支。
echo.
pause
exit /b 1

:open
start http://localhost:8710/
