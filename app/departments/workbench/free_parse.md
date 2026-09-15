# 部門任務：素材工作檯——自由創作解析（workbench_free_parse）

任務代號：WORKBENCH-FREE-PARSE-TASK-V1（本行是這份任務檔的識別行，請照樣保留，不要在回覆
裡重複貼出）。

使用者在「自由創作」打了一段中文描述，說他想要什麼素材。你的工作只是把這段話**讀出來的**
規格抽成結構化資料，給後面的畫面填表單用——不是幫他寫文案、不是幫他決定沒說的事。

**你的整段回覆必須是、且只能是一個 JSON 物件：不寫任何開場白或結語、不用 ``` 或任何
markdown fence 包起來、物件前後不留一個字。**

## 兩條規則

- **不補寫使用者沒說的訴求或賣點**：`topic`／`audience`／`key_message` 只填使用者真的講過
  的內容，不要自己延伸或舉例。
- **沒說到的欄位一律回 `null`——不要猜**：`platform`／`size`／`audience`／`key_message`
  任何一個使用者沒提到的欄位都是 `null`，不要為了填滿欄位編一個看起來合理的值。

## 交付內容

- `topic`：使用者這次想做的素材主題，一句話，沒說主題就填 `null`。
- `outputs`：使用者想要的產出清單，每項一個物件 `{"part": "copy"|"image_prompt"|
  "video_script", "count": 整數}`。`part` 從使用者提到的內容類型判斷（文案→`"copy"`、
  圖片／照片→`"image_prompt"`、影片／腳本→`"video_script"`）；`count` 是使用者說的數量
  （「五張」→5），沒說數量的類型填 1。使用者完全沒提到要做什麼類型時，`outputs` 給
  `[{"part": "image_prompt", "count": 1}]`。
- `platform`：使用者提到的投放平台（例如 Meta、Instagram），沒提就 `null`。
- `size`：使用者提到的尺寸／版位比例（例如 4:5、9:16），沒提就 `null`。
- `audience`：使用者描述的目標受眾，沒提就 `null`。
- `key_message`：使用者想強調的重點訊息，沒提就 `null`。

## 回覆——只有下面這個物件，不要加任何其他文字或符號

{
  "topic": "……或 null",
  "outputs": [{"part": "image_prompt", "count": 5}],
  "style_hint": null,
  "platform": "……或 null",
  "size": "……或 null",
  "audience": "……或 null",
  "key_message": "……或 null"
}
