# 切片看板（只放未開始＋進行中；完成即刪行，歷史＝git log）

排序＝執行順序。分票唯一依據＝`docs/ui-migration-contract.md` v2（含隨批裁決）＋ ADR 0019。
標「需批准」的票動工前先提計畫等批准；動到畫面先過畫面契約（草圖 → 後端 → 前端）。

- [>] O1-01 調度台本體：decide()＋派工員＋決策留痕（第一條垂直線；票 .scratch/orchestrator/issues/03；**已批准新表 `decision`**，資料庫已備份）①凍結✓ ②審查通過✓ ③待你驗收
- [ ] M1-01 Meta MCP 整期一鍵建（**暫緩，2026-08-23**）：連線與參數都已驗證可用，但 Meta 以錯誤 31／子碼 3858385 擋住「用 API 建立或修改廣告」——已知的 Meta 端問題（開發者社群 thread 845129991936233），後台看不到待辦事項、無入口可完成驗證，後台手動操作不受影響。系統使用者 token 未被 Ads MCP 文件列為支援，未驗證。改走 ADR 0023 保留的手填 ID 路徑；Meta 端解除後本票即可續跑。
- [ ] M1-02 收件匣同意即執行（停用／降額；加碼再一道金額確認）＋安全底線（需批准；被 M1-01 擋）
- [ ] M1-03 放手檔執行器（需批准；被 M1-02 擋）
- [ ] P1 成效回流接通：帶單切角下期加權＋反回音室自動避開（兌現 nextcycle 既有承諾；**必須在 M1 之後**——切角歸因依賴 M1 回寫的 external_ad_mapping，ADR 0022 第 6 條）
- [ ] T1 最終閘門不穩定：`pytest -n auto --dist loadfile` 每次隨機紅 1–2 條、每次不同條（2026-08-23 三次實測：`test_ads_compliance` 的 DefaultHoldTest／UnbackedClaimDefaultHoldTest、`test_dashboard_guide_card_links`；乾淨 HEAD 一樣紅＝既有問題）。疑點：`creative.list_variants()` 順序來自主題排序，測試用 `[0]` 抓第一筆，時間戳同秒即不保證。**禁止用跳過標記或放寬容忍清單處理**。
- [ ] U1 新手五鐵則落地：全站術語大掃除＋禁用詞機器閘門＋步驟指示常駐（契約鐵則 11–12 驗收）；含鐵則 9 清理——weekly 通知雙出口（dashboard/repository.py:207，票 06 起既有）
