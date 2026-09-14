# 系統整理品牌知識：第一次「格式讀不成預期的樣子」；worker 沒註冊 task 時畫面永遠「已等 0 秒（通常）」

Status: 2026-09-14 F05 收尾走查（站 4）量到。

事實：
- `intake_research` 第一次 llm_task succeeded（29 s）但 `apply_paste` 解析失敗，畫面：「AI 有回覆，但格式讀不成預期的樣子…
  再試一次」；第二次成功（25 s）。提示詞對表格格式的約束不夠硬（沿用外部 AI 那套「|」分隔規格）。
- 若跑的 worker 是舊程式（沒註冊 `background.intake_research`），佇列 job 9 ms 內 failed、沒有 llm_task 列，
  畫面停在「正在整理品牌知識：，已等 0 秒（通常），可以先離開這裡」——stage 與「通常」範圍都是空字串，不報錯。
- 真相卡把「單一核心產品／服務定位」當成售價題（`truth_card.is_price_item` 靠關鍵字「定位」？要查）。

做法（未裁決）：研究提示詞改要求 JSON 或在程式端容錯一次重試；佇列 job failed 而無 llm_task 時畫面要印「工作沒有被
接走，請確認背景工作程序」；`is_price_item` 的關鍵字表縮緊。
