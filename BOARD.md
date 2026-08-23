# 切片看板（只放未開始＋進行中；完成即刪行，歷史＝git log）

排序＝執行順序。分票唯一依據＝`docs/ui-migration-contract.md` v2（含隨批裁決）＋ ADR 0019。
標「需批准」的票動工前先提計畫等批准；動到畫面先過畫面契約（草圖 → 後端 → 前端）。

- [>] V1-01 這期的優惠入口（開期表單填＋檔期頁可改；契約 `.scratch/v1/TICKET-V1-01.md`，無 migration）：`offer` 表與讀取端早就在（`theme_engine.py:148`），全站沒有寫入端，開期固定寫死 `offer_id=None`（`repository.py:139`）。第①站已過。
- [ ] V1-02 脈動有沒有照做，機器要抓得到：現在自動對帳只比總花費不比每日預算（`reconcile.py` 檔頭：各幣別單位換算不一，比錯就狼來了），使用者不照排程調日預算抓不出來，只有對帳三題自答（`guardrails.py:157`）答「不一樣」才會降可信度。要機器自動抓，得讓 `build_actuals` 撈回 Meta 的每日預算——**被 M1-01 擋**。
- [ ] M1-01 Meta MCP 整期一鍵建（**暫緩，2026-08-23**）：連線與參數都已驗證可用，但 Meta 以錯誤 31／子碼 3858385 擋住「用 API 建立或修改廣告」——已知的 Meta 端問題（開發者社群 thread 845129991936233），後台看不到待辦事項、無入口可完成驗證，後台手動操作不受影響。系統使用者 token 未被 Ads MCP 文件列為支援，未驗證。改走 ADR 0023 保留的手填 ID 路徑；Meta 端解除後本票即可續跑。
- [ ] M1-02 收件匣同意即執行（停用／降額；加碼再一道金額確認）＋安全底線（需批准；被 M1-01 擋）
- [ ] M1-03 放手檔執行器（需批准；被 M1-02 擋）
- [ ] P1 成效回流接通：帶單切角下期加權＋反回音室自動避開（兌現 nextcycle 既有承諾；**必須在 M1 之後**——切角歸因依賴 M1 回寫的 external_ad_mapping，ADR 0022 第 6 條）
- [ ] T1 最終閘門不穩定：`pytest -n auto --dist loadfile` 每次隨機紅 1–2 條、每次不同條（2026-08-23 三次實測：`test_ads_compliance` 的 DefaultHoldTest／UnbackedClaimDefaultHoldTest、`test_dashboard_guide_card_links`；乾淨 HEAD 一樣紅＝既有問題）。疑點：`creative.list_variants()` 順序來自主題排序，測試用 `[0]` 抓第一筆，時間戳同秒即不保證。**禁止用跳過標記或放寬容忍清單處理**。
- [ ] U1 新手五鐵則落地：全站術語大掃除＋禁用詞機器閘門＋步驟指示常駐（契約鐵則 11–12 驗收）；含鐵則 9 清理——weekly 通知雙出口（dashboard/repository.py:207，票 06 起既有）
