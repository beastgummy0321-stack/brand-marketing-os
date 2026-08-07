---
來源: marketingskills/ads 2.2.0（SKILL、conversion-tracking）＋ 2026-08-07 D2C 改寫
（meta-decision-system 為 B2B 名單型文件，已移出來源；其 TCPL 倍數門檻全部改以自家目標 CPA 與打平 CPA 定錨）
最後查證日: 2026-08-07
---

# 廣告方法論：Meta 投放－電商特有規則

只在**有商品、走站內交易**時適用。平台通用規則見 `ads-core.md`；健康類／受法規管制品類政策見 `ads-health.md`。

## 1. 毛利與成本上限

- **打平 ROAS／成本天花板**：**打平 ROAS = 1 ÷ 毛利率**（毛利 60% → 1.67；50% → 2.0；40% → 2.5）。再把顧客終身價值算進去，得出能負擔的最高取得成本。擴量擴到接近天花板為止，而不是擴到 ROAS 掉破某個主觀偏好值就停。這是 `ads-core.md` 第 6 節「成本上限」在電商情境下的算法。
- **回檔觸發**：擴量後每筆購買成本觸到**打平 CPA ＝ 客單價 × 毛利率**（賺的錢剛好全付給廣告）→ 立刻砍預算 20–30%，穩定 2 週，再以每週 +10% 恢復。

## 2. Advantage+ 購物活動（ASC）

**電商現行的預設結構**，素材照 `ads-core.md` 第 1 節的產能基準持續補。有複購結構就設**既有顧客預算上限**，避免演算法把錢灌進本來就會發生的再行銷轉換（比例自己依複購佔比定，官方無建議值）。

## 3. 投放前檢查清單（電商特有）

- [ ] Meta Pixel 已安裝在全站頁面
- [ ] 標準事件已設定：PageView、ViewContent、AddToCart、InitiateCheckout、Purchase
- [ ] 網域已驗證，Aggregated Event Measurement 前 8 大事件優先序已設（Purchase 通常第 1）
- [ ] 購買事件在「確認付款成功／感謝頁」才觸發，不是按鈕點擊；已排除內部團隊流量

其餘一次性檢查項（Business Manager、Conversions API、Event Match Quality、特殊廣告類別）與每期必看清單見 `ads-core.md` 第 8 節。
