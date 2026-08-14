# 目前任務

**agency-model 分支：產品模型翻新（ADR 0018）——後端無前置票全數完成，等使用者開畫面契約**

- 依據：`docs/adr/0018-agency-model.md`＋`docs/ui-migration-contract.md` v2（分票唯一依據）
- 票：`.scratch/agency-model/issues/`（30 張；done/ 8 張：02/05/06/07/21/24/28/29）
- 已落地：判讀與結算自動排程、週提案卡＋一鍵核可＋保卡修正、月報數字 API、自動度設定
  （fail-safe 鐵則入契約 §7）、配碼降備援、初代原型刪除、測試撞庫根治（conftest 隔離）
- **下一步全部等使用者**：①畫面契約 grill（票 01/08/10/16/23，解鎖其餘全部）②票 25 顧問報告
  去留裁決 ③補驗：設定頁自動度兩顆按鈕人工看一眼＋Chrome 擴充放行本機網址
- 節奏不變：Codex 實作→獨立 Sonnet 驗證→仲裁 commit；退回超過 3 輪停線（票 21 用掉 1 輪）
- master 停在翻新前（4cbb857），整套可回退
