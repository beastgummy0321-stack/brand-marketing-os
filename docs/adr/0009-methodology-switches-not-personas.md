# 方法論不預設使用者身分：人設只填預設值，開關才是機制

舊規則：`app/methodology/` 六個檔從第一行就寫死使用者身分——`ads.md` 開頭宣告「只收 Meta」、
「金額一律用 NT$」，投放前檢查清單把 `AddToCart`／`InitiateCheckout`／`Purchase` 列為必填，
打平公式寫死 `打平 CPA ＝ 客單價 × 毛利率`，`creative-matrix.md` 要求人物「一律寫成台灣面孔」，
Hook 範例十一組全是雞精。逐條盤點共五層汙染、約 100 行綁死「台灣保健食品 D2C 電商」。

推翻理由：使用者 2026-08-07 grill 指出——這套 OS 不得預設誰在用。KOL、B2C、C2C、服務業，
不論有無帶產品，只要要投廣告就該能用。上一輪（commit `9eb7351`）為了拔掉 B2B 名單型汙染，
把借來的 TCPL 門檻改成「客單價 × 毛利率」，等於拔掉一個預設又裝進另一個預設。

## 一、開關是機制，人設是填表捷徑

四個開關決定方法論檔載不載入：`有商品`、`站內交易`、`有自有網站`、`健康類法規`
（`app/brand_intelligence/repository.py` 的 `compute_methodology_switches()`）。
其中三個讀既有資料（`product`／`owned_channel`／`brand_fact`），只有 `站內交易` 讀新欄位。

人設（KOL／品牌商家／個人賣家／服務預約／其他）**只是一次填好四個開關預設值的捷徑**，
存成程式常數（`app/mock_data.py` 的 `PERSONA_SWITCH_DEFAULTS`），**不進 DB、不進 prompt**。

理由：人設與行為不是一對一——KOL 可能有自有聯名商品，品牌可能只做導流。
若人設是機制（DB 存「這是 KOL」、方法論查人設），「有商品的 KOL」就必須新增一個人設，
被逼進窮舉；開關是機制時，同一個人改一個開關即可，人設表永遠只有五列。

## 二、開關值一律平台中立

`brand.conversion_goal` 只收 `purchase`／`lead`／`booking`／`awareness`，
**不得存 Meta 事件名**——Meta 專屬欄位名只能關在 `app/ads/meta_api.py`（該檔第 14 行的平台隔離原則）。
平台中立值 → Meta 標準事件的對照表寫在 `app/methodology/README.md`，該檔不會被組進 prompt，
寫在那裡不必付 token。

`brand.market_region` 用 ISO 3166-1 alpha-2；目前只有 `TW` 有對應的方法論內容。

## 三、條件載入語法，README 對照表是唯一權威

`app/methodology/README.md` 的「任務型別 → 必讀方法論檔對照表」，檔名後可加全形條件括號：

    | 檔期計畫生成 | `ads-core.md`、`ads-commerce.md`（需要：有商品）、`ab-testing.md` |

全形括號 `（）` ＋ 全形冒號 `：`，由 `app/llm/methodology.py` 的 `_FILE_RE` 解析。
半形冒號不會匹配、該檔會被當成無條件檔案永遠載入，**不報錯、不變紅**——這是唯一的靜默失效點，
本輪實作時真的踩到過（兩個 agent 對同一份規格寫出不同全半形）。

`ads.md`（121 行）依此拆成 `ads-core.md`（通用平台機制）／`ads-commerce.md`（毛利公式、
購物車事件、Pixel 清單）／`ads-health.md`（Meta 健康類政策）。

**與 ADR 0001 的關係（不是推翻）**：0001 拒絕 progressive disclosure，因為模型沒有工具、
指路標會指到它到不了的地方。本則的條件載入是**程式在呼叫 API 前**依 DB 算好的，模型不參與、
不會多讀一次檔；被選中的檔案仍是整份原文注入，檔案**內部**照樣不做指路標。
0001 的 Consequences 原本寫「沒有『用不到就不載入』這條路」，該句已同步補註。

## 四、開關為 NULL ＝ 不成立，不倒填猜測值

原本鎖的契約是「開關為 NULL → 不過濾、全部載入（＝維持今天的行為）」。
實作時被推翻成「缺資料就是缺資料，視為不成立」，**接受這個推翻**。

理由：誠實狀態優先於向後相容。倒填成「成立」等於在資料缺失時假裝知道答案，
正是這輪要修掉的那個 bug 的成因。代價是既有品牌要去設定一次，
用駕駛艙引導卡明顯提醒（`app/dashboard/guide_cards.py`）。

## 五、`lead`／`booking`／`awareness` 不預先萃取方法論

這三種轉換目標目前沒有專屬方法論檔，只拿得到 `ads-core.md` 的通用平台機制。
依 `app/methodology/README.md` 維護規則「只按消費拉動萃取」——沒有真實使用者在用就不預先寫，
死文件只會增加維護負擔。README 的「待建置」一節記錄了這個缺口。

## 當時排除了什麼

- **依人設注入不同範例庫**：使用者原本的提法。排除理由見第一節（窮舉、人設≠行為）。
  改成範例一律骨架化（`你不是不{被誤解的行為}，你只是{真正的阻礙}`），
  品類語感由 `app/llm/context_compiler.py` 既有的品牌自有資料提供，方法論檔不再舉例。
- **把開關存進 `brand_fact`**：零 migration，但 `brand_fact` 只有 `status='confirmed'` 才進 prompt，
  建檔精靈跑到一半的品牌會沒有值 → 方法論門檻拿不到輸入 → 退回舊預設，靜默錯誤。
- **在方法論 `.md` 裡寫條件標記讓程式過濾**：要寫 marker parser，且整檔照樣進 prompt、省不到 token。
  拆檔零新增 parser，且 KOL 少吃約 44 行。
- **接建檔精靈收開關**：要在 `app/intake/` 開一條繞過人工確認的落庫特例。改用品牌編輯頁兩個下拉，
  單機單人一個品牌設定一次即可；欄位已在，日後要接建檔精靈不必改 schema。
- **串 Meta 廣告檔案庫 API 看競品**：查證後不可行——`ad_type=ALL` 只在歐盟／英國回商業廣告，
  台灣只回政治與社會議題廣告；Google Ads Transparency Center 的商業廣告完全沒有官方 API。
  第三方逆向工程端點在平台 ToS 之外，不採用。
