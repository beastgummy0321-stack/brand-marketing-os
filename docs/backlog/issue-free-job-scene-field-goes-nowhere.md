# 自由創作的「場景」欄位填了沒人收

2026-09-12，F02 整合審查記下的保留席位（不是 bug，是還沒接的線）。

`frontend/src/components/workbench/FreeJobPage.tsx` 的 精準控制 有 場景 欄位（參考圖 4 有畫），
使用者填得進去，但 `PreciseControl.scene` 是純本頁狀態：`spec` 的七個鍵沒有它（F02 Decisions
「精準控制's 人物／場景 have no `spec` field」），`specToCreateBody()` 也不送。同一排的 人物 會
對到 `spec.audience` → `coordinates.audience`，場景不會——所以兩個看起來一樣的欄位，一個有用一個沒用。

為什麼先不接：場景要真的生效得進圖片提示詞的 ①主圖 組裝（ARCHITECTURE.md §5.8 的
`【畫面】`／`hero`），那是模型自己回的欄位，不是表單欄位；要讓表單蓋過模型，得先決定「人填的場景
是硬約束還是提示」。這是產品決定，不是接線。

接的時候一起決定：
- 場景要不要跟 人物 一樣落成 set 的座標／`request`，還是變成 `hero` 的預設值？
- 蓋過模型之後，`SetDetail.generation_settings` 的 場景 那一列要顯示誰的值（§5.13 現在讀
  `body_json["hero"]["scene"]`）？
- 在那之前，欄位要不要標一句「之後接上」（比照圖片生成港口那條 `image_generation.reason`），
  免得使用者以為填了有用。
