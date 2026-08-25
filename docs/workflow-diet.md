# 工作流減重（2026-08-26 grill 定案 Q33／Q34）

給另一個 session 執行。規則本體在 skeleton-slice plugin 的 workflow.md（SessionStart 注入），
專案層覆寫寫進本專案 `CLAUDE.md`「Tests」節與 `AGENTS.md`。

## 量測依據

- 後端 38,605 行 / 測試 43,802 行（1.13×）；前端 25,131 行 / 測試 143 行。
- 最近 40 commit：36 個 route C（開票＋獨立審＋全套閘門），含純文案修改；route A 只用於錯字。
- 全套 `pytest -n auto --dist loadfile` ≈ 200 s，每票每次跑；7 個測試檔硬卡 800 行上限。

## 改動（5 條）

1. **分流門檻**
   - route B（機器閘門綠＝完成，免獨立審）擴大為：不動 schema、不動模組進入點
     （`status／handle／active_jobs`、`routes*.py` 的 include）、不動花錢／權限路徑的**所有行為修改**。
   - route C 只留：schema／migration、模組邊界、金流、權限／租戶隔離。
2. **閘門範圍**
   - 每張票只跑受影響的測試檔（`pytest app/tests/test_<module>*.py`）＋ typecheck ＋ build。
   - 全套 2,400 條只在合併進主線時跑一次。
3. **800 行上限不適用於測試檔**：拆測試檔沒有價值，移除 `KNOWN_OVERSIZED_FILES` 對 `app/tests/` 的檢查。
4. **測試瘦身原則**（資料層一次翻時執行）
   - 刪：斷言畫面文案等於某字串的測試；同一行為多份只差 fixture 的重複測試。
   - 留：資料正確性、金額計算、租戶隔離、模組邊界、API 契約形狀。
   - 目標：測試行數 ≈ 程式 0.7×。
5. **前端補一條端到端 smoke**（Playwright 已裝）：登入 → 建品牌 → 開檔期 → 看到駕駛艙。
   之後前端行為改動的機器閘門＝typecheck ＋ build ＋ 這條 smoke。

## 不變

- 機器閘門紅＝未交付，不進審查。
- 禁止放寬容忍清單或改測試遷就壞行為。
- 實作者與審查者必須是不同 agent（route C）。
