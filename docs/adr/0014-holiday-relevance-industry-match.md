# 節日相關性：業種標籤自動比對，永久覆寫掛進設定中心

_Status: retired by ADR 0030 — the code it governed was deleted._

G7（2026-08-10 grill）。查證現況：`campaign_calendar_data.json` 每筆事件只有
`{id, name, date, tier}`，`brand` 表沒有業種欄位，`app/dashboard/campaign_calendar.py`
全部函式純日期數學，沒有任何相關性判斷——目前每個節日對所有品牌一視同仁地提醒。
`guide_cards.py` 全模組無狀態（明文「只讀 facts，不寫入任何表」），沒有任何提醒類型有
覆寫/忽略機制。

## 一、系統自動比對業種標籤，不要求使用者每次判斷

`brand` 表新增 `industry` 欄位（沿用 `market_region`／`conversion_goal` 已確立的做法：
ALTER TABLE + enum 限制值，見 `app/brand_intelligence/migrations/0005_brand_switches.sql`
先例）。`campaign_calendar_data.json` 每筆事件新增 `applicable_industries` 欄位（業種清單，
或 `"all"` 表示對所有業種都相關，例如雙11／618 這類全民購物節）。品牌業種出現在清單內，
或事件標 `"all"`，才判相關、正常提醒；否則不提醒。

## 二、永久覆寫（打破 guide_cards 無狀態原則，需要新表）

使用者可以把「某個節日類別」永久標記為「跟我無關」，之後系統自動比對判成相關也不再提醒；
可在設定中心重新開啟。**這是 guide_cards 系列第一個需要持久化狀態的提醒類型**——新增小表
（例如 `brand_dismissed_calendar_category`，`brand_id` + `event_id` 或分類鍵），
`campaign_calendar.py` 的比對邏輯讀這張表再決定最終要不要提醒。

**跟 G8 的邊界**：永久覆寫解決「系統業種判斷錯了」；G8「這期跳過」解決「這次剛好不投，
下次還是要提醒」——兩者資料儲存與語意都不同，不合併成一個機制。

## 三、覆寫介面掛進 G14 設定中心，不另開新畫面

管理已忽略節日類別的介面，加進「廣告層面」分類底下新的「節日提醒」小節，沿用 G14 已驗收
的欄位列樣式（標籤＋說明＋開關），不需要另外走一輪畫面契約——這是既有已定案畫面的自然
延伸，不是新的使用者互動模式。

## 當時排除了什麼

- **使用者手動勾選哪些節日跟自己有關**：查證後改成系統依業種標籤自動比對，理由是不該
  要求使用者每次自己判斷本來系統就查得出來的事。
- **覆寫只關今年、明年還提醒**：排除，理由見第二節——業種判斷錯是持續性的錯，不是
  單期事件，跟 G8 的語意不同，分開處理。
- **覆寫另開一個新畫面**：排除，直接掛進剛定案的 G14 設定中心，重用其欄位列樣式。
