---
來源: app/creative/format_specs.py（票 G1-A，2026-08-08 grill 定案）；各節末列 Meta 官方連結
最後查證日: 2026-09-09
---

# Meta 版位格式規格表

素材生成任務的硬規格。這裡的數字**有官方出處**（每節末列連結與查證日），與外殼切片要移除的
猜測門檻不同——猜測門檻沒有來源，這些有。

目錄廣告刻意不進表（2026-08-08 定案：降級為排期建議）。CTA 與連結不生成：多商品輪播每卡連結
＝組裝時帶既有商品資料，屬組裝範圍，不是生成欄位。

目標維度五個鍵：`awareness` / `traffic` / `engagement` / `leads` / `sales`。

## 1. 單圖 single_image

- 比例 4:5，1080×1350（查證日 2026-08-07）
- 視覺方向：每個廣告節點 1 份，不分品項變體另產（ADR 0047）。內容＝七維座標＋一個
  `visual_tone`＋一到兩句話的畫面概念，由文案任務決定（`app/departments/workbench/copy.md`，
  ADR 0068 §5 amendment），這裡不重複規格，也不是給圖片工具直接貼上生圖的完整提示詞
- `body`：三種長度各出——短 100～150 字 ×5、中 300～500 字 ×3、長 800～1000 字 ×2（ADR 0068 §8；Meta 硬上限 1024 字元／則，asset_feed_spec，2026-09-09 查證）。125 字是折疊線，鉤子放前面；Reels 版位約 40 字即截斷，不另設變體
- `title`：5 個，27 字。Meta 顯示截斷約 27–40 依版位而異，取最嚴 27 當品質預算
- `description`：5 個，30 字

每主題媒體上限：`sales` = **10**（彈性格式）；`awareness` / `traffic` / `engagement` / `leads`
= **1**（文字仍出 5 個，走多文字最佳化）。

來源：
- https://developers.facebook.com/docs/marketing-api/flexible-ad-format/ （2026-08-07）
- https://developers.facebook.com/documentation/ads-commerce/marketing-api/ad-creative/asset-feed-spec （2026-08-07）
- https://www.facebook.com/business/help/2579898108796785 （2026-08-08，多文字最佳化不限購買目標）

## 2. 輪播 carousel

- 比例 1:1，1080×1080
- 卡片數 2–10
- 敘事型態：`steps` 步驟型（卡片數＝步驟數）、`before_after` 對比型（固定 2 卡）、
  `multi_product` 多商品型（卡片數＝商品數）
- 視覺方向：沿用該廣告節點唯一的一份（見「1. 單圖 single_image」），不逐卡另產
- `card_title`：每卡 1 個，45 字
- `card_description`：每卡 1 個，20 字（業界整理的顯示截斷值，Meta 官方規格未明列，查證日 2026-08-08）
- `body`：5 個，80 字（廣告層，非卡片層）

每主題媒體上限：五種目標皆 **1**（每主題＝一套敘事＝一則廣告）。

來源：https://www.facebook.com/business/ads-guide/carousel （2026-08-08）

## 3. 影片 video

- 比例 9:16，1080×1920
- 預設長度 30 秒（出自 `creative-matrix.md` 第 5 節「時間軸以 30 秒為基準，依實際長度等比縮放」）；
  上限不硬性宣告，由所選框架決定
- `script`：每切角 3 支，至少跨 2 框架，無字數預算
- `hook_pool`：每切角 10 個，跨腳本共用，無字數預算
- `body`：5 個，125 字
- `title`：5 個，27 字
- `description`：5 個，30 字

每主題媒體上限：五種目標皆 **1**（主題＝腳本）。

來源：https://www.facebook.com/business/ads-guide/video （2026-08-08）

## 4. 快速生成四類

素材工作檯「快速生成」入口，是上表既有欄位的子集，不新增欄位定義。四類都不含
`title` / `description`（使用者明確排除）。

| 類型 | 基底格式 | 欄位 |
|---|---|---|
| 完整貼文 post | single_image | 視覺方向、`body` |
| 完整影片 video | video | `hook_pool`、`script`、`body` |
| 單張圖片 image | single_image | 視覺方向 |
| 單則腳本 script | video | `hook_pool`、`script` |
