# 開機自動啟動（票 F6）

決策：2026-08-25 使用者裁決「開機自動啟動」（歷史決策 R5-S）。機制是 Windows 內建的
工作排程器（Task Scheduler／`schtasks`），觸發條件是 `onlogon`——**登入 Windows 時**
啟動系統，不是「電腦一直開著背景默默跑」。

使用者明確要求設定自動啟動時，agent 可在主機權限允許下建立或更新此一般使用者排程；先查同名工作，避免覆寫別人的設定。主機權限要求仍適用。也可自行執行下面指令一次。

## 這支排程器實際上做什麼

叫用的是 `app/tools/boot_launcher.py`，不是「啟動行銷系統.bat」：
- 用 `pythonw.exe`（不是 `python.exe`）執行，登入當下不會跳出黑底 cmd 視窗搶焦點，
  也不會自動開瀏覽器分頁。
- 先探測 port 8710 是不是已經有人在聽（例如你自己手動點了 `啟動行銷系統.bat`），
  有的話就直接結束，不會重複啟動第二個 process。
- 也會把 worker（`python -m app.worker`，ADR 0063）當成這個 process 的子行程開起來；
  `關閉行銷系統.bat` 用 `taskkill /PID … /T` 收掉聽 8710 那個 process 時，`/T` 會連著
  把 worker 一起收掉，不需要另外處理。worker 自己的訊息寫進 `logs/worker.log`。
- 啟動器只監看自己建立的 worker：非零異常退出或無法啟動時，依序等待 2、5、15 秒，
  最多重啟 3 次；不會無限重試。正常退出（包括另一個 worker 已持有資料庫鎖）不重啟。
  達到上限仍保留網站，錯誤留在 `logs/worker.log`。啟動器正常離開時停止監看，
  終止自己仍在執行的 worker。Windows 使用明確自有 PID 的 `taskkill /T /F`，
  連同虛擬環境啟動殼下的實際 Python 一起結束，不按名稱搜尋其他 worker。
  每次終止命令與退出等待各限 5 秒，未退出最多再嘗試一次，失敗記錄於日誌。
- 執行過程的訊息寫進 `logs/boot_launcher.log`（這支 log 檔不進版控）。

worker 取得資料庫 schema 的唯一鎖後，才處理上次中斷的工作。只自動重排明確列入
唯讀清單的來源同步與監看工作，保留原佇列識別及參數；外部同步沿已保存游標續讀，
舊 Meta 每日／回補工作仍依原有規則重新計算日期範圍。已要求中止的工作不復活。
檢討工作先解除孤兒佇列狀態，再由廣告模組恢復已保存結果或保留結果未知；
不因 worker 重啟就重送已可能付費的模型請求。網站正在執行的模型工作不納入 worker
中斷掃描。連線網址及 key=value 格式的其他參數都保留，只切換佇列專屬 search_path。
每次啟動最多回收 10 批、每批 100 件已知孤兒工作；沒有進展就停止。仍有剩餘時明確
記錄數量，需後續重啟續接，不會把未完成的恢復顯示為全部完成，也不在運行中掃描活工作。

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

## 怎麼確認真的生效了

agent 可查工作定義、手動觸發與檢查日誌／頁面；真正登出再登入由使用者安排，不為驗證打斷目前工作。

1. 貼上面「建立排程」那條指令。
2. 把電腦登出再重新登入（或直接重開機、登入）——不必等，`onlogon` 是登入當下就觸發。
3. 打開瀏覽器，開 <http://localhost:8710/>：能打開就是成功了。
4. 打不開的話，看 `logs/boot_launcher.log` 最後幾行有沒有錯誤訊息；也可以在工作排程器
   GUI 裡點 `MarketingOS-AutoStart` → 「歷程記錄」分頁看有沒有觸發過、觸發後的結果碼。
