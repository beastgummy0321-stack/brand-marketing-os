# 全站搬家契約總表（2026-08-11 定案，ADR 0017）

搬家與廣告強化的分票唯一依據。視覺沿用駕駛艙設計系統（tokens.css）；互動照第二節五鐵則。
每批依 `~/.claude/screen-contract.md` 三段走：可點原型（假資料）→ 使用者驗收 → 後端補接口 → 接線。
每個畫面的逐條契約條文與線框放 `.scratch/grill/`（用完即刪），票券引用條文編號。

提案視覺版（含草圖）：https://claude.ai/code/artifact/9a4f25f3-d992-4ef1-b556-01153d22e76d

## 一、新版整站地圖（15 個畫面）

| # | 畫面 | 狀態 | 吸收的舊頁 |
|---|---|---|---|
| S1 | 跨品牌總覽 | 已完成 | index.html（品牌卡部分） |
| S2 | 收件匣 | 搬家 | inbox.html、首頁「今天要處理的事」、prototype_phase.html |
| S3 | 駕駛艙 | 已完成 | — |
| S4 | 品牌建檔精靈 | 搬家 | intake/ 全部 9 頁、brand_new.html |
| S5 | 品牌智庫（六分頁＋側板） | 搬家 | hub_* 7 頁＋fact/rule/claim/channel/asset/voice 新增編輯確認 12 頁＋brand_edit.html |
| S6 | 產品清單＋產品詳情 | 搬家 | product_hub 系列 6 頁、economics_form、product_new/delete/handoff |
| S7 | 檔期清單 | 搬家 | ads_home、ads_history、ads_interview |
| S8 | 檔期作戰室（任務流） | 搬家＋強化 | ads_new、ads_progress、ads_plan_select、ads_cycle、ads_checklist、ads_handoff、ads_checkpoint、ads_performance、ads_performance_data、ads_cycle_delete |
| S9 | 週報 | 全新 | —（掛在作戰室內） |
| S10 | 連線與資料 | 搬家 | ads_connections、ads_claims、ads_ga4*、ads_pixel_guide、ads_data_migration |
| S11 | 累積智慧 | 搬家 | ads_learnings |
| S12 | 素材工作檯 | 部分完成＋收斂 | ads_creatives 退役（ADR 0017 收斂①） |
| S13 | 顧問報告 | 搬家 | report、report_progress、report_export |
| S14 | 訂單資料 | 搬家 | orders_home |
| S15 | 設定 | 搬家 | settings、settings_hub、settings_ads |

品牌刪除／產品刪除保留二次確認＋刪前備份；404/500 為通用件。

## 二、全站互動五鐵則（蓋所有畫面）

1. **一路下一步**：流程畫面中央只放目前該做的一件事；AI 預填＋推薦選項＋單一主按鈕。
2. **清單不換頁**：新增／編輯／確認一律側板滑出，清單原地即時更新。
3. **AI 生成不擋路**：生成轉背景，畫面可離開；完成後通知＋收件匣留底；全站生成進度單一出口。
4. **按了一定有反應**：點擊 100ms 內有視覺回饋；送出中鎖按鈕；失敗一律人話＋可重試。
5. **空狀態會帶路**：無資料顯示「這頁幹嘛＋第一步按鈕」；首次進站 30 秒導覽。

## 三、廣告強化（隨批次一起做，總綱第四節體檢表為驗收基準）

KPI 對齊漏斗（S8 開檔）、預算拆層＋排期策略三選一（S8 企劃）、命名與 UTM 檢查（S8 交接）、
QA 升級成系統自動覆核（S8 交接）、週報六段式（S9）、結案覆盤固定格式（S8 覆盤）、
學習期重置規則進規則卡（S11）、檔期日曆第一層（S3 指南卡；若已落地則略過）。

## 四、分批交付

| 批 | 內容 | 前置 |
|---|---|---|
| B1 | S2 收件匣＋S15 設定 | — |
| B2 | S5 品牌智庫＋S6 產品 | B1 定調側板互動 |
| B3 | S4 建檔精靈 | B1 |
| B4 | S7 檔期清單＋S8 作戰室（含企劃強化、QA 升級） | B2 |
| B5 | S9 週報＋S10 連線與資料＋S11 累積智慧＋覆盤格式 | B4 |
| B6 | S12 素材收斂＋S13 顧問報告＋S14 訂單＋雙軌退役 | B4 |
| 切換 | 總綱體檢表全綠 → 舊 Jinja 頁下線、「回舊版」移除 | B1–B6 |

每批交付順序固定：契約條文＋可點原型 → 使用者驗收 → 補 JSON 接口 → 接線 → 獨立驗證＋1440px 瀏覽器實測 → commit。
