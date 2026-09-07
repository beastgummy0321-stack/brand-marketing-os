# 樹說預算掛在第二層，Meta 上錢掛在第一層——沒有任何一步發現

Status: 開著——2026-09-07 真跑查核時，拿 Graph 讀回綁定好的活動與組合才發現。
不是算錯錢，是**核准過的分配沒有被執行，而且下一輪判讀會把 Meta 的自動分配當成使用者的決定**。

## 成因

`app/schedule/tree.py` 的契約裡 `budget_level` 指出哪一層扛預算（Meta＝2、Google＝1，資料不是常數），
每個扛 `share` 的節點比例加起來要等於 1.0，否則整棵樹失敗（`_SHARE_SUM_TOLERANCE`）。
2026-09-07 核准的那棵樹：`budget_level: 2`，三個廣告組合 `share` 是 0.55／0.20／0.25。

實際去 Meta 讀回來（`GET /v21.0/<id>?fields=daily_budget,...`）：

```
d1 行銷活動  {"objective": "OUTCOME_SALES", "daily_budget": "500"}
d2 廣告組合  {"optimization_goal": "OFFSITE_CONVERSIONS"}      ← 沒有 daily_budget
d2 廣告組合  {"optimization_goal": "OFFSITE_CONVERSIONS"}      ← 沒有 daily_budget
d2 廣告組合  {"optimization_goal": "OFFSITE_CONVERSIONS"}      ← 沒有 daily_budget
```

錢在第一層（Meta 的 Advantage 行銷活動預算，俗稱 CBO），第二層一毛預算都沒設。
**55／20／25 這個核准過的決定沒有在執行**，Meta 自己決定要把 500 元怎麼分給三個組合。

從頭到尾沒有一步會發現：
- 展開／核准只算 `share` 加起來是不是 1.0，不知道使用者之後會怎麼在 Meta 設。
- 配對（`bind_tree()`）只比對名稱，不讀 `daily_budget`。
- 每日拉取只抓花費數字，不抓預算欄位。

## 影響

1. **核准形同虛設。** 使用者在畫面上按「核准」核准的是 55／20／25，Meta 上跑的是別的東西。
2. **⑨ 的「錢」那一維會學到錯的因果。** 判讀比較的是「哪個座標值花了多少、賺了多少」。
   在 CBO 底下，Meta 會自動把錢挪向它認為會轉換的組合——所以「這個座標花得多」的成因是
   Meta 的最佳化器，不是使用者的計畫。系統會把 Meta 的選擇當成自己的實驗結果讀。
   這正好打到 T6c 決定 3／`ab-testing.md:72-75` 想避免的那件事：拿觀察值當對照實驗。
3. 這一條不會讓任何一個數字算錯，所以機器閘門與現有測試都不會紅。

## 修法（要裁決的是第 3 條）

1. **配對成功之後讀一次預算欄位**：對 `budget_level` 那一層的每個綁定節點抓 `daily_budget`／
   `lifetime_budget`，全是空的就在畫面上講一句「你的預算掛在第 N 層，這棵樹是照第 2 層分配的，
   核准的 55／20／25 不會生效」。一次 Graph 呼叫，配對本來就在打 Graph。
2. 產生名稱清單給使用者去 Meta 建的時候，把「預算要設在廣告組合層、每個組合多少錢」一起寫出來——
   現在畫面只給名字，金額要使用者自己從百分比換算。
3. **要裁決**：CBO 底下要不要乾脆不出 `share`？還是照出、但把「這一輪的分配由 Meta 決定」寫進
   判讀的輸入，讓它知道花費差異不是實驗結果？兩條路對 ⑨ 的意義完全不同，這是使用者的決定。

`file:line`：`app/schedule/tree.py`（`budget_level`／`share` 的契約）、
`app/schedule/binding.py:73-140`（`bind_tree()`，只比對名稱）、
`app/meta/graph.py`（拉取欄位清單裡沒有預算）。
