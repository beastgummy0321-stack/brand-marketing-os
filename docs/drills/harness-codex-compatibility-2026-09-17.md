# Planner Harness：Codex 最小相容修復

日期：2026-09-17（台灣時間）。範圍：插件相容性與專案指引；未實作 marketing 產品功能，未領取、合併或關閉 F07。

## 計畫與落地

1. 補齊 PreToolUse / PostToolUse matcher 的 `exec_command`、`shell_command`，讓既有 host 轉接器支援的 shell 名稱能被設定匹配。
2. status 對未關閉 Feature 顯示 `Closure: open (not closed)` 與人工驗收項目數。保留 queue next 的既有回傳格式；佇列完成不等於結案。
3. 新增根目錄 AGENTS.md，指向 CLAUDE.md 共用規則；更新舊版流程、未收到 SessionStart 的續接方式與本機插件來源解析方式。
4. 新增三項回歸測試，通過後重新安裝本機插件。

插件修改檔：`hooks/hooks.json`、`lib/status.mjs`、`test/compatibility.test.mjs`。
開發來源：`D:\0UserProfile\Desktop\Default\Planner`。
Codex marketplace 安裝來源：`C:\Users\User\plugins\harness`。
安裝版本：`3.0.0+codex.20260916223941`；安裝來源的版本後綴由官方 helper 更新，開發來源保留 3.0.0。
舊 `Default\harness` 未修改；未 commit、push 或更新 Claude 安裝。

## 實測證據

| 檢查 | 結果 |
| --- | --- |
| 新增回歸＋既有 portability 測試 | 7/7 通過 |
| 插件 `npm test` 完整測試 | 43/43 通過，無跳過 |
| 官方 validate_plugin.py | 通過；PyYAML 使用 uv 獨立環境，未改專案依賴 |
| 重新安裝後的 compatibility 測試 | 3/3 通過 |
| 開發來源與新安裝快取 hooks.json SHA256 | 相同 |
| marketing：新版 CLI validate | valid |
| marketing：新版 Python 架構檢查器 | 退出碼 0，無違規輸出 |
| marketing：status | F07 未關閉、人工驗收 5 項、done 15、無 active/ready/blocked |
| marketing 與插件 git diff --check | 通過 |
| marketing 的 .work 與 ARCHITECTURE.md 差異 | 無 |

本輪已允許實作與測試，因此 CLI validate/status 正常追加忽略版控的 metrics；它們不是嚴格唯讀指令。
破壞性命令測試只把 `git reset --hard` 當作字串送入 hook，並未執行該命令。

## 證據邊界與下一次原生驗證

完整測試涵蓋暫存 Git 倉庫中的工作樹、授權、檢查器、驗證失敗修復與 Feature lifecycle；不等於 Codex 桌面原生派工或 hook 接線端到端通過。

本輪未證明桌面 App 自動送出 SessionStart / PreToolUse / PostToolUse，也未證明所有工具封裝方式都會觸發 matcher。插件技能可載入不能作為上述證據。

重新安裝不會重載當前對話。下一次在 marketing 開新對話，以唯讀檢查確認新技能位置與 AGENTS.md 入口；原生 hook 的攔截驗證應使用獨立暫存專案與可追溯事件紀錄，避免拿 F07 或真實破壞性操作測試。缺少主機事件證據時仍標示未驗證，以主機權限與 CLI 最終檢查作為現有邊界。
