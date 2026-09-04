# T6c 第⑨步後半：三個 agent 的診斷

Status: blocked-on-data——開票條件是**至少兩個不同的座標值真的花到錢**，今天是 0 元。
關聯：ADR 0057 §6（程式先壓縮、AI 只判斷、程式排序取前 5）；前半（座標賺賠圖）2026-09-04 已合併（route B，零行後端）。

## 為什麼還不開票

有座標的花費今天是 0 元（探針量的），圖上一顆泡泡都沒有；就算把綁上的那則廣告打開也只有一顆，
一顆泡泡在七個維度裡會被印成七次一模一樣的數字。**三個 agent 判 n=1 會出看起來很權威、實際上
是猜的建議**（24-agent／130 條建議那次的教訓）。沒有這一步，使用者拿到的是一堆數字不是「下一輪
該做什麼」，違反憲法第 4 條。要達到開票條件做的人是使用者（把廣告 02／03 貼進 Meta 並打開）。

## 開工時仍然有效的讀數陷阱

- 廣告層 `effective_status` 有 12 個值，`DISAPPROVED`／`PENDING_REVIEW` 的花費是 0，**在座標表上
  長得跟「這個角度沒人要」一模一樣**（ADR 0057 §8）。圖那一半已處理（零花費的座標不畫、一句話交代），
  agent 這一半要自己再處理一次。
- `roas` 有兩個都成立的分母（`docs/contracts/schedule.md` Measured），agent 拿到的壓縮數字要帶覆蓋率，
  不能只給一個 ROAS。
- `spend_summary` 的 `bool_and` 讓整支回 None——**擋不到這裡**：`app/schedule/performance.py:26`
  明文「絕不重用」，自己用 `daily_entity_spend` 算。修 `spend_summary` 本身會動到核准煞車
  （`tree_approval.py:98`）與駕駛艙，是另一張錢的票。
- `roas` 最小 0.4196、最大 50，賠錢的列有；打平線畫在 ROAS **=1** 不是 0。
- `echarts.ts` 已註冊 `ScatterChart`／`MarkLineComponent`／`MarkAreaComponent`；陷阱仍然成立：
  漏註冊會靜默不畫而閘門全綠，加新圖種要真的看一眼。
- `daily_pull.py:89` 拉 `[今天-7, 今天]`（理由在 `:54`），歸因窗 7d_click 沒有洞（2026-09-02 查證）。
