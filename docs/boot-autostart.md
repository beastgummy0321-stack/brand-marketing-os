# 開機自動啟動（票 F6）

決策：2026-08-25 使用者裁決「開機自動啟動」（BOARD.md R5-S）。機制是 Windows 內建的
工作排程器（Task Scheduler／`schtasks`），觸發條件是 `onlogon`——**登入 Windows 時**
啟動系統，不是「電腦一直開著背景默默跑」。

這一步需要系統管理權限，Claude／agent 不會幫你按下去——下面兩段指令你自己貼進
PowerShell 或命令提示字元執行一次即可，不需要每次開機都做。

## 這支排程器實際上做什麼

叫用的是 `app/tools/boot_launcher.py`，不是「啟動行銷系統.bat」：
- 用 `pythonw.exe`（不是 `python.exe`）執行，登入當下不會跳出黑底 cmd 視窗搶焦點，
  也不會自動開瀏覽器分頁。
- 先探測 port 8710 是不是已經有人在聽（例如你自己手動點了 `啟動行銷系統.bat`），
  有的話就直接結束，不會重複啟動第二個 process。
- process 一起來就會先補跑一次到期檢查（`app/main.py _auto_sync_if_due`），把機器
  關著這段時間漏掉的 14 天最終結算追回來，不必等滿一小時的輪詢間隔。
- 執行過程的訊息寫進 `logs/boot_launcher.log`（這支 log 檔不進版控）。

## 建立排程（貼一次就好）

把下面整條指令貼進 PowerShell 執行（`/tn` 是工作名稱，之後查詢／刪除都用這個名字找）：

```powershell
schtasks /create /tn "MarketingOS-AutoStart" /tr "\"C:\Users\User\AppData\Local\Programs\Python\Python312\pythonw.exe\" \"D:\0UserProfile\Desktop\marketing\app\tools\boot_launcher.py\"" /sc onlogon /rl limited /it /f
```

參數說明（不用背，供想知道在幹嘛的人看）：
- `/sc onlogon`：觸發條件是「登入 Windows」，不是固定時刻，也不是「開機」本身
  （沒人登入就不會有任何動作——這是誠實的邊界，不是漏洞）。
- `/rl limited`：用一般使用者權限跑，不用系統管理員權限開網頁伺服器。
- `/it`：只有互動式登入才觸發（不會在沒人坐在電腦前的情境下嘗試跑）。
- `/f`：同名工作已存在就直接覆蓋，不會因為「已經有一個」而報錯中斷。

若你的 Python 沒有裝在上面那個路徑，先在 PowerShell 執行 `(Get-Command pythonw).Source`
查出實際路徑，把指令裡 `pythonw.exe` 那段換掉再貼。

## 失敗不會每次登入跳一次對話框

`schtasks /create` 預設不會在啟動失敗時彈對話框；上面的指令也沒有加任何會跳提示的
選項。要是想讓失敗自動重試，Task Scheduler 圖形介面（工作排程器）裡該工作的「設定」
分頁有「如果工作失敗，依照以下設定重新啟動」可以勾，這是選用的，不是必要條件。

## 在哪裡看得到、怎麼刪掉

- 工作排程器 GUI：開始功能表搜尋「工作排程器」（Task Scheduler）→左側「工作排程器程式庫」
  （Task Scheduler Library）→找 `MarketingOS-AutoStart`。
- 命令列查詢：

  ```powershell
  schtasks /query /tn "MarketingOS-AutoStart"
  ```

- 命令列刪除（不需要先停用，直接刪）：

  ```powershell
  schtasks /delete /tn "MarketingOS-AutoStart" /f
  ```

  刪掉之後下次登入就不會再自動啟動；已經在跑的 process 不受影響，要停照舊方法點兩下
  `關閉行銷系統.bat`。

## 怎麼確認真的生效了（人工，agent 沒辦法幫你按這步）

1. 貼上面「建立排程」那條指令。
2. 把電腦登出再重新登入（或直接重開機、登入）——不必等，`onlogon` 是登入當下就觸發。
3. 打開瀏覽器，開 <http://localhost:8710/>：能打開就是成功了。
4. 打不開的話，看 `logs/boot_launcher.log` 最後幾行有沒有錯誤訊息；也可以在工作排程器
   GUI 裡點 `MarketingOS-AutoStart` → 「歷程記錄」分頁看有沒有觸發過、觸發後的結果碼。
