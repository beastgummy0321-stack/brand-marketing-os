# 刪四個沒人用的欄位

Status: before-cloud——2026-09-05 從 `docs/tech-debt.md` §七認領進上雲目標（使用者裁決：上雲前全清）。
路線：route C（schema，需批准）。

**需批准（schema）四個沒人用的欄位**：`order_record.attribution_override`、`interrupt.kind`／`visible_from`／
`campaign_cycle_id`；欄位還在所以 `enqueue()` 那三個沒有生產呼叫端的參數也還留著。`decision` 表 2026-09-01
改判不刪（要當「建議落表」，形狀剛好）。
