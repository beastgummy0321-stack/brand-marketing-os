# 部門任務檔自己跟自己打架：七維「都要填」vs「除了 angle 一律給 null」

Status: ask-user——`app/departments/` 是提示詞零件，刪改先問（專案 CLAUDE.md）。
發現於：`docs/issues/ad-loop/issue-same-name-leaf-node-key.md` 那張票，順手讀到，不在那張票的範圍。

成因：`app/departments/creative/ad_creative.md` 同一份檔案裡有兩句相反的話。
「交付內容」那節寫 **「七個都要填」**（`app/departments/creative/ad_creative.md:28`）；
檔尾的 JSON 格式說明卻寫 **「`coordinates` 除了 `angle` 之外目前一律給 `null`」**
（同檔 `:81`）。後面那句是票 T1 時代的殘留，T1b／T8b 把七維真的接上之後沒有刪掉。

影響：今天沒有咬到人——2026-09-04 實查 `brd_bughunt` 最新六個候選，七欄全部有值
（`audience_key='cold_problem_aware'`、`proof_key='none'` …）。原因是座標詞彙表那一節排在
prompt 的**最後**（票 T8b 量出來的位置效應），壓過了這句殘留。但這是一句站在原地的地雷：
`jobs.py` 那個 `"\n\n".join` 的段落順序只要有人動一次，代理就可能改聽這句，七維全變 `null`，
而**所有機器閘門都會是綠的**——畫面照樣長得像功能還在動，⑨ 的整套診斷同時變空。

修法：刪掉那半句（一行 diff）。要問的只有一件事：這是提示詞零件，刪改先問。
