# Drill 8 — 重跑 B 側（F39＋F40 之後），量四件事（2026-09-30）

目的：同一套腳本、評審、品牌事實（`../drill-6/brand-facts.md`），只換系統版本（master `aeb1812c`：F39 座標學習／成績表／每則情境／行事曆進文案，F40 前端批次），重跑 B 三期，對照 drill-6、drill-7 的 A 與 B。**演練中不修程式**。

沿用：`../drill-7/plan.md` 的每期流程、`../drill-6/contract.md`、`judge-rubric.md`、`persona-beast.md`、`../drill-4/persona-rules.md`、`.harness/scratch/drill7/judge-prompt.md`。

## 只換了什麼

| 項 | drill 7 | drill 8 |
|---|---|---|
| A 側 | 沿用 drill-6 | 同（`rows_A_1..3`、`fit_A_1..3` 逐位元相同） |
| B 系統 | master `3ecc16fb` | master `aeb1812c`（F39、F40） |
| B 帳號 | beast.drill7@example.com | 新註冊 `beast.drill8@example.com`（新組織） |
| 期別 | P1 9/26–10/2、P2 10/3–10/9、P3 10/10–10/16；P1 規劃日早於真實日期 | **整體往後 7 天**：P1 10/3–10/9、P2 10/10–10/16、P3 10/17–10/23；規劃日都晚於真實日期 9/30（drill-7 §3 #17 的教訓） |
| 模擬 | 產品日期＝A 日期 | 兩套：**實際日期**（灌回替身、persona 看到的數字）＋**對齊 A 窗**（`tw_sim --start/--end` 減 7 天，星期幾相同，只用來跟 A 比） |
| 後端 | `drill-backend`＋`scripts.drill.worker` | 同；worker 用 `Start-Process` 獨立行程 |

期別挪動的代價：模擬器行事曆（`tw_sim.CALENDAR`）與 A 同一套 9/26–10/16；B 的產品行事曆（`app/ads/calendar_tw.py`）看到的是挪後的一週（國慶落在 P1 尾／P2 頭、P3 沒有節日）。「對齊 A 窗」那套數字把 B 的計畫放進 A 的那一週跑，行事曆情境可能錯位一週；報告兩套都列、A-vs-B 表用對齊那套。

## 四個量測

1. 第二、三期規劃是否沿用第一期划算的座標組合，並在 `rationale` 點名（F39 只是 prompt 規則；沒照做 → 建議改成 `plan._validate_reply` 程式閘門）。證據：`ads_campaign`／`ads_ad` 的座標、strategy `basis.coordinate_scoreboard`、plan rationale。
2. 不同受眾的 `ads_ad.scene` 不同，文案跟著情境（評審「名實不符」扣分次數）。
3. 行事曆出現在 hook（國慶／期中考／連假字樣）。
4. F40 畫面是否消掉 drill-7 §3 #7–#18 的摩擦站（逐條對照 persona 分數與原句）。

## 執行中的修正（演練工具）

`scripts/drill/export_plan.py` 讀素材文案時沒限定現行版本，改過文案的廣告匯出成第一版。已改讀 `is_current`，三期重匯重評重模擬；灌回替身的仍是修正前的數字（報告 §1）。
