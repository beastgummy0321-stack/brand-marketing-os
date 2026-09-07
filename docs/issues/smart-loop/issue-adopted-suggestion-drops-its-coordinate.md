# 「採用」把建議的座標鍵丟掉，下一期算得出成效卻接不回那條建議

Status: found 2026-09-07 by code probe (three sonnet probes, not docs). Blocked on data: tagged spend is
still 0, so nothing here is verifiable until at least two coordinate values have spent money.
Related: `issue-adopt-has-no-echo.md` (§3 "判讀不記得" is the user-facing symptom of this).

## 成因（file:line）

- `converge()` 的每條建議本來就帶 `dimension`／`coordinate_key`／`direction`／`impact_spend`
  （`app/schedule/diagnosis.py:348-352`、去重鍵 `:363`）。
- 「採用」只把 `headline`＋`evidence` 揉成文字寫進 `rule.content`（`diagnosis.py:428 adopt_content`、
  `app/schedule/routes.py:536-547`）；`rule` 表沒有任何結構欄位可放座標鍵
  （`supabase/migrations/20260826000002_brand_intelligence_baseline.sql:141-154`），`source_reference_id` 因 FK 留 NULL。
- 方案←規則這段是通的：`llm_task.knowledge_item_ids_json` 存了 prompt 吃到的規則 id（`app/llm/gateway.py:121-139`）。
  斷的是規則→座標值→下一期數字這段。

## 影響

系統無法回答「上次採用的那條，後來對不對」。沒有這個答案，規則只能按新舊排（`app/llm/context_compiler.py:49-57`，
cap 20、`confirmed_at` 建立即設、overflow 無消費端），不能按結果汰舊；判讀壓縮表也無法多一欄「上次採用＋結果」。
「越用越聰明」卡在這一公尺。

## 已驗證的周邊事實（開票前不必再查）

- 排程管線已存在：`app/meta/daily_pull.py:154-156` 有 procrastinate `periodic()`，cron `0 3 * * *`（`:46`）。
  新的週期工作照這個樣板掛，不另開 plumbing。背景任務共 9 個，不是 4 個。
- 跨期查詢便宜：`meta_repo.daily_entity_spend()` 吃任意起迄（`app/meta/repository.py:636-637`），
  只有 `performance.py:199` 釘死在 `state._current_month_window`。開一個視窗參數即可。
- 兩種「期」並存且未對齊：日曆月（`state.py:97-105`）與 `campaign_period.start_date/end_date`
  （`20260903000001_schedule_campaign_period.sql:9-29`）。記分要選哪一種是站①決定。
- 實體→座標的 join 在 Python 做，不在 SQL（ADR 0057 §1，`app/schedule/repository.py:608-635`）。
- T6c 決定 10：判讀觸發＝按鈕，不自動跑；全自動回流已否決。記分（純算術、不花錢、不叫 LLM）不在該否決範圍，
  自動跑 LLM 判讀才在。
- ADR 0012 半活半死（cap 活、過期死），自己檔頭已註明；碰這題時一併裁決留或退。

## 最小一刀（未裁決，route C：碰資料模型）

1. 站①：schedule 模組自己一張表（不動 brand_intelligence 的 `rule`）：`rule_id` FK、`dimension`、`coordinate_key`、
   `direction`、`round_date`、採用當下的 `impact_spend`；判定結果依憲法第 7 條用日期區間列，不就地更新。
2. 記分＝純算術：採用日之後 vs 之前，同座標值的花費／ROAS 方向 → 對／反／沒資料。掛在每日拉取之後。
3. 記分餵回兩處，不加規則、不加 lens：壓縮表多一欄「上次採用＋結果」；已判定的 experiment 規則退出 prompt。
4. 自動跑判讀：留一顆開關預設關（憲法第 3 條），開不開由使用者裁決，不由票決定。
