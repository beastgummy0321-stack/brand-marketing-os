# 檔期頁只看得到當下那一期，上一期整個從畫面消失

Status: 2026-09-06 可用性演練量到（`docs/drills/`），從
`issue-coordinates-lost-when-next-period-planned.md` 拆出來——那條的**資料歸屬**已由 slice-10
（ADR 0064）修掉，這條是它剩下的**畫面**部分，後端沒有東西要改。

成因：排程頁只讀「最新那一列 `schedule_plan`／`schedule_tree`」（`app/schedule/state.py` 的
`_display_task_row()`），畫面上沒有任何切換、沒有清單、沒有歷史入口。出下一期方案之後，
上一期的日期、方案文字、活動樹**完全不在畫面上**。

使用者看到的：小杰搜「歷史」「切換」「所有檔期」零結果；他上一期是**已核准、真的花過
5,270 元**的。他的話：「我完全不知道現在畫面上的東西跟 Meta 裡實際在跑的還對不對得起來。」

不是資料沒有：`campaign_period` 一期一列、`llm_task` 每一輪生成各自留著、`channel_entity_map`
從 ADR 0064 起每棵樹各自留著自己的綁定。**資料全在，缺的只是一個看得到它的畫面。**

`file:line`：`app/schedule/state.py:78-88`（`_display_task_row` 只取最新一列）、
`frontend/src/components/schedule/SchedulePage.tsx`（沒有任何期別切換）。

做法（未裁決）：檔期切換是新畫面／新狀態，照 `/slice` 分流要走「新畫面或新狀態」那一列
（先做假資料版＋這份 issue 升票）。要先裁決的是形狀：頁首一個期別下拉、還是一條時間軸？
切到舊期時「產素材／綁定」這些會寫入的按鈕要不要整批鎖掉（強烈建議要）？

前端紅線（`docs/design-system.md` §1）：這一頁已經有分頁，歷史不得做成再往下長的第二段。
