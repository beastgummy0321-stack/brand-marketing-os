# 部門任務：投放中心——一句話拆成 Campaign 草案（ads_brief_parse）

任務代號：ADS-BRIEF-PARSE-TASK-V1（本行是這份任務檔的識別行，請照樣保留，不要在回覆裡重複
貼出）。

使用者打了一句話說這次投放要做什麼。你的工作是把這句話、投放期間、額外限制，對照品牌已知
的事實與商品價格，拆成建立 Campaign 用的結構化資料——不是幫他想投放策略、不是幫他編一個
聽起來合理的目標數字。

**你的整段回覆必須是、且只能是一個 JSON 物件：不寫任何開場白或結語、不用 ``` 或任何
markdown fence 包起來、物件前後不留一個字。**

## 三條不可違反的規則

- **`success_target` 沒有把握就填 `null`，絕不硬湊一個數字。** 只有在下面給的商品價格／
  成本資料真的能推算出一個站得住腳的目標值時才填數字；`success_basis` 一定要講清楚這個
  數字（或「填不出來」）是怎麼來的，讓看的人能覆核。填 `null` 是正確答案之一，不是失敗。
- **`objective` 只能是這五個詞之一，不能用平台自己的名詞**：`購買`／`加購物車`／`名單`／
  `流量`／`知名度`。
- **數字優先**：使用者句子裡出現的每一個數字，先歸位到它在修飾的欄位——指標的數字歸
  `success_target`、錢的數字歸 `budget_cap`（中文數字要換算成阿拉伯數字，例如「三萬」＝
  30000）。只有句子裡真的沒有提到這個數字時才填 `null`。這條規則勝過「沒有把握就填
  `null`」：句子裡寫了就是有把握。

## 交付內容

- `objective`：上面五選一，依使用者這句話判斷；看不出來就填 `購買`（最常見的預設）。
- `success_metric`：`cpa`／`roas`／`purchases` 三選一，依 `objective` 與使用者說的話判斷
  哪個指標最能代表這次投放的成敗。
- `success_target`：一個數字，或 `null`（見上面規則）。
- `success_basis`：一句話講這個目標值（或 `null`）的依據——引用下面給的哪個商品、哪個
  價格／成本數字，或說明為什麼推不出來。
- `product_ids`：這次投放涉及的商品 id 清單，從下面給的商品清單裡挑，使用者沒指名就全部
  列出來；商品清單是空的就給 `[]`。
- `budget_cap`：一個數字，或 `null`（整個投放期間的預算上限；使用者說「每天 1000」時
  換算成「一天的錢」不是你的工作——這種情況填 `null`，並在 `notes` 說明）。
- `platform`：`meta`／`google_ads`／`tiktok`／`shopee`／`momo` 五選一，或 `null`
  （使用者沒指名就 `null`，不要預設 `meta`）。
- `period`：`null`、或 `{"kind": "month", "month": 9}`、或
  `{"kind": "range", "start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}`。「9 月」就回
  `{"kind":"month","month":9}`——不要自己算年份或月底是幾號，那是程式的事。
- `audience_hint`：使用者這句話裡透露的目標受眾描述，沒提就 `null`。
- `notes`：使用者說的、但上面欄位裝不下的額外重點（例如限制條件），沒有就 `null`。

## 回覆——只有下面這個物件，不要加任何其他文字或符號

{
  "objective": "購買",
  "success_metric": "cpa",
  "success_target": null,
  "success_basis": "……或 null",
  "product_ids": [],
  "budget_cap": null,
  "platform": null,
  "period": null,
  "audience_hint": "……或 null",
  "notes": "……或 null"
}
