---
id: 0012
decision: Unconfirmed rules expire out of the prompt and only a capped set enters it; the overflow is shown, not hidden.
applies-to: [app/llm/context_compiler.py, app/core/rule_cards.py]
supersedes: none
status: in-force
---

# 品牌智庫規則加有效期與 prompt 上限，不再無限累積

_Status (re-verified 2026-09-02): **half of this ADR is live, half is gone.**_

- _**Live:** the prompt cap. `app/llm/context_compiler.py:_select_rules_for_prompt` reads the
  `rule_prompt_cap.max_active_rules` card (default 20) and `hard` rules bypass the cap._
- _**Gone:** the expiry sweep. `app/brand_intelligence/rule_lifecycle.py` and the `rule_expiry`
  card no longer exist; nothing sweeps a rule back to 待確認 today. The mechanism is described
  below as designed, not as built._
- _ADR 0037, which amended both, was retired by ADR 0046 — red lines are now a post-generation
  exclusion list, and rejected angles are `feedback` rows (ADR 0050). Do not read 0037's
  amendments as in force._

G5（2026-08-10 grill）。查證現況：`app/llm/context_compiler.py` 把 `rule` 表全部
`status='active'` 的規則無條件整包塞進「【限制】規則」段落，無上限、無排序、無過期——
規則只會隨時間單調增加。

## 一、有效期＝6 期（約 3 個月）

`rule` 表新增 `confirmed_at`（新增欄位）。每次通過確認即更新；超過 6 期（`campaign_cycle`
預設 14 天／期）未被重新確認 → 狀態退回 `pending_reconfirm`，不進 prompt，但不刪除、
不自動變 `inactive`——使用者到累積智慧頁一鍵「延續」即可，不必重新輸入內容。

6 期取自一般商業慣例的季度回顧頻率，非外部平台規格，屬內部政策設計，不需另外查證來源。

## 二、進 prompt 上限＝20 條，超額依 `severity` 排序

`context_compiler.py` 的規則注入邏輯改為：`hard` 規則全部保留；`soft` 規則依
`confirmed_at`（越新越優先）排序，超過 20 條的部分不進 prompt。`severity` 是 `rule` 表
既有欄位（`hard`/`soft`），沿用既有分類，不新增排序邏輯。

## 三、超額不悄悄丟棄，累積智慧頁顯示

超過上限而未進 prompt 的規則，累積智慧頁顯示「有 N 條規則因超過上限未生效」，附清單。
呼應 ADR 0009 一貫的「誠實狀態優先」原則。

## 當時排除了什麼

- **維持現況、不設有效期**：查證後発現規則只會單調累積，這題本來就是「規則膨脹的防線」，
  沒有汰舊機制等於防線不存在。
- **超額規則自動刪除或隱藏**：改成顯示「未生效」清單，理由同第三節。
