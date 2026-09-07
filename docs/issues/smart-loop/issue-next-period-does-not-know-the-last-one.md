# 下一期方案完全不知道上一期：每期一棵新樹、名字現寫、綁回同一個活動只靠巧合

Status: found 2026-09-07 by code probe. Blocked on data (同 spec.md)。
Related: `docs/issues/ui/issue-period-page-has-no-history.md`（畫面那一半）。

## 成因（file:line）

- 每次 `POST /tree` 生一列全新的 `schedule_tree` `llm_task`，每次讀都從 `rendered_output` 重算（`app/schedule/tree.py:7-8`）；
  節點 `name` 直接取 LLM 輸出（`tree.py:79-80`），只有 `node_key` 是決定性的（`tree.py:76`）。
- 綁定靠名稱完全相符（`app/schedule/binding.py:73-126`，`campaign_ids_by_exact_name`）；對不到就 0 命中失敗（`:114-115`）。
- plan prompt 的上下文只有品牌知識（`app/llm/context_compiler.py`），零引用 `campaign_period`／`schedule_tree`／`channel_entity_map`。
- Schema 已允許同一個 Meta 活動跨期重綁（ADR 0064 §2；`20260906000001_schedule_binding_per_tree.sql:20-22`）。
- `app/meta/` 唯讀（只有 `list_*`／insights），系統建不了活動。

## 影響

使用者每期都要去 Meta 重貼一整套名字；表現好的活動累積的學習與歷史在 Meta 端斷掉；
系統學到的東西（記分）沒有地方接回「下一期哪些節點留、哪些換」。

## 最小一刀（未裁決，route B，前提是 spec 第 1、2 刀已落地）

- plan prompt 末段加一張小表「上一期：節點名｜七維座標｜花費｜ROAS（保守／樂觀）｜記分結果」，
  來源 `channel_entity_map`＋`creative_candidate` 七個 `*_key`＋記分表；行數＝上期節點數（今天 ≤10）。這不是資料包。
- 延續規則（站①裁）：記分「對」或「沒資料」的節點，名字原樣帶進下一期，讓名稱綁定自動接回；「反」的節點換座標、換名字。
- 畫面：樹上標「延續」／「新」；綁定頁只列「新」的要你去 Meta 建。
