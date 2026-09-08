---
來源: 各檔 frontmatter
最後查證日: 2026-08-07
---

# 方法論檔索引

`app/methodology/` 是**程式零件**：`app/llm/methodology.py` 依下方對照表，把指定的檔案**整份原文**組進生成 prompt。每一行在每次生成時都要付 token。

## 檔案索引

| 檔案 | 內容 |
|---|---|
| `ads-core.md` | Meta 投放核心（平台中立）：現行打法、受眾、帳戶結構、出價與學習期、素材疲勞、擴量紀律、再行銷、投放前清單 |
| `ads-commerce.md` | 電商特有：毛利與成本上限公式、ASC、購物事件與 Pixel／網域檢查清單 |
| `ad-creative.md` | 三種生成模式、grounding 要求、15 款樣板、Meta 字數規格 |
| `ab-testing.md` | 樣本數速查表、Peeking 紀律、ICE 排序 |
| `copywriting.md` | 五大原則、寫作規則、CTA、Hook 公式、改寫範例、心理模型 |
| `creative-matrix.md` | 35 個創意角度、真人實拍 DNA、產圖硬規則、Hook 切法、影片腳本框架 |
| `meta-format-specs.md` | Meta 版位格式規格表：單圖／輪播／影片的比例、欄位數、字數預算、每主題媒體上限（自 `app/creative/format_specs.py` 移出） |
| `customer-voice.md` | 顧客原話抽取規則、台灣在地管道 |
| `humanizer-zh-tw.md` | 去 AI 味規則：核心速查、個性與靈魂、14 個內容／語言模式改寫前後對照 |
| `image-prompt-template.md` | 圖片提示詞模板：八段可替換模組、14 行輸出格式、固定段／變動段切法、200–250 字規則 |

## 任務型別 → 必讀方法論檔對照表

檔名後可加一個條件括號，只有品牌對應開關成立才載入：`` `檔名.md`（需要：開關名） ``——
**全形括號 `（）` ＋ 全形冒號 `：`**，半形寫法 regex 不會匹配，會被當成無條件檔案靜默載入。
開關名只有四個可用：`有商品`、`站內交易`、`有自有網站`、`健康類法規`（見
`app/brand_intelligence/repository.py` 的 `compute_methodology_switches`）。沒帶條件的檔案一律載入。

| 任務型別 | 必讀方法論檔 |
|---|---|
| 檔期計畫生成 | `ads-core.md`、`ads-commerce.md`（需要：有商品）、`ab-testing.md`、`customer-voice.md` |
| Hook／文案生成 | `ad-creative.md`、`copywriting.md`、`creative-matrix.md`、`customer-voice.md` |
| 圖片 Prompt 生成 | `creative-matrix.md`、`ad-creative.md` |
| 影片腳本生成 | `creative-matrix.md`、`copywriting.md` |
| 成效判讀／下期草案 | `ab-testing.md`、`ads-core.md`、`ads-commerce.md`（需要：有商品） |
| 期中檢查點 | `ab-testing.md`（禁判勝負節） |
| 廣告內容生成 | `creative-matrix.md`、`meta-format-specs.md` |
| 素材工作檯文案 | `copywriting.md`、`humanizer-zh-tw.md`、`customer-voice.md`、`meta-format-specs.md` |
| 素材工作檯圖片提示詞 | `creative-matrix.md`、`image-prompt-template.md` |
| 素材工作檯影片腳本 | `creative-matrix.md`、`copywriting.md`、`humanizer-zh-tw.md` |

## 平台中立值 → Meta 標準事件對照

本產品內部用平台中立的轉換目標命名（`brand.conversion_goal`：`purchase`／`lead`／`booking`／`awareness`），投 Meta 時對照到官方標準事件：

| 平台中立值 | Meta 標準事件 |
|---|---|
| `purchase` | Purchase／AddToCart／InitiateCheckout |
| `lead` | Lead／CompleteRegistration |
| `booking` | Schedule |
| `awareness` | 無對應標準事件 |

出處：Meta Pixel 標準事件官方參考文件 <https://developers.facebook.com/docs/meta-pixel/reference>（2026-08-07 查證）。

## 待建置

- 海外市場目前沒有內容，只有台灣：`customer-voice.md` 的台灣管道表、`creative-matrix.md` 真人實拍 DNA 的台灣面孔／場景描述。海外品牌先用中性描述或請人工補，不要自行推測當地內容。
- `conversion_goal` 的 `lead`／`booking`／`awareness` 三種目標目前沒有專屬方法論檔，只提供 `ads-core.md` 的通用平台機制。依本檔「只按消費拉動萃取」規則，有真實使用者再萃取。

## 維護規則

- **每檔要有最後查證日**（frontmatter），記錄上次核對來源的日期。不設到期提醒、不進前端收件匣——使用者在介面上做不完重萃取這件事。
- **會過期的數字一律改寫成相對自身基準**（「較這支素材自己的高峰跌 30%」而非「概念壽命 2–3 週」）。相對值拿自家數據當分母，永不過期。不能相對化的只有平台硬規格與政策，那些由平台當場回饋（截斷、拒登），不需要日曆提醒。
- **上游更新＝人工重萃取**，來源在 `reference/marketingskills/`，不做自動同步。
- **新增檔要同步改上面兩張表**，不能只加檔案不更新索引。
- **只按消費拉動萃取**：沒有分支在用的方法論不要預先萃取，死文件只會增加維護負擔。
- **每檔 150 行上限**（`test_methodology.py` 把關）。超過就砍，不要放寬。
- **數字要有出處**：不在 `reference/` 樹裡的外部數字一律登記在下表。查不到出處的數字不得留在方法論檔裡。

## 外部來源登記（不在 `reference/` 樹裡的數字）

本檔不會被組進 prompt（`methodology.py` 只解析上面的對照表），所以網址寫在這裡不必付 token。

| 方法論位置 | 數字 | 出處 |
|---|---|---|
| `ads-core.md` §3 帳戶 2–3 個活動 | 月花費 $1K–10K 建議 2–3 個活動 | <https://benly.ai/learn/meta-ads/ad-account-structure>（分級表，非 Meta 官方） |

**2026-08-07 移除的外部數字**（改用相對自身基準或直接刪，不再需要維護）：產能基準每週 3 則（Motion Creative Benchmarks 2026）、ASC 每次購買成本低 5%（Meta 官方頁；2023 年的 17% 為舊說法）、概念壽命 2–3 週與 10 天衰退曲線（`adlibrary.com/posts/ad-fatigue`，業界回報值）。要查原始數字回這個 commit 的訊息。

**2026-08-07 ads.md 拆檔**：`ads.md` 拆成 `ads-core.md`／`ads-commerce.md`／`ads-health.md`，原檔已刪除，內容對應見上方檔案索引表；歷史沿革查這個 commit 前的版本。

**2026-08-29 ads-health.md 刪除**（ADR 0036）：健康類／受法規管制品類的廣告政策整份刪掉，產品不再於程式裡帶任何產業法規知識。品牌要避開的說法寫成品牌規則，由 `context_compiler` 進每一份 prompt。
