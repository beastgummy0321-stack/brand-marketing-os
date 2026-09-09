# 配對有 11 個節點成功、1 個新節點找不到，畫面卻只說「配對失敗」

Status: open，2026-09-08 越排越好票 04 驗收走查量到。

成因：`app/schedule/binding.py` `bind_tree()` 回傳的是失敗清單，成功的節點已寫進 `channel_entity_map`（資料庫證實：
新樹 `llm_01M1YSN3…` 綁上活動 1、組合 3、廣告 7），但 `bind_failure_message()` 只組失敗那句，`routes._run_bind()`
在清單非空時整批回錯誤（`app/schedule/routes.py:342` 附近），前端 `CampaignTree.tsx` 因此只顯示紅字
「配對失敗：「04｜…」在 Meta 上找不到…」，沒有任何一處說「其餘 11 個已接回上一期的物件」。

影響：贏家延續（票 04）落地後，每一期的樹都會同時有「延續」（已綁）與「新」（要去 Meta 建）兩種節點，
這個畫面會讓使用者以為整批失敗、去 Meta 重建已經存在的東西。

修法（route B，畫面＋一句文案）：成功數與失敗清單一起回（`bind` 端點回 `{bound: n, failures: [...]}` 或沿用既有
回應多帶一個數字），前端顯示「已接回 11 個節點；1 個新節點要去 Meta 建：04｜…」；樹上「延續上一期」徽章旁補「已配對」狀態。
`docs/design-system.md` 用字。
