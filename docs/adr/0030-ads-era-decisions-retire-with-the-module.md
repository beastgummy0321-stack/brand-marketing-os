---
id: 0030
decision: ADRs that governed deleted ads code are retired, not deleted — the record is the vaccine.
applies-to: [docs/adr/]
supersedes: 0016
status: in-force
---

# Ads-era decisions retire with the module

`app/ads/` (21,595 lines) and its 81 test files are deleted and replaced by a prompt shell
(ADR 0028, 0029, `HANDOFF-shell-slice.md`). Twelve earlier ADRs decided the behaviour of code
that no longer exists. They are **retired, not deleted** — each keeps its body and gains a
`Status` line pointing here.

Retiring rather than deleting is the point. Every one of these recorded a threshold or a rule
that was guessed and never validated against a real campaign. Delete the record and the next
person re-derives "可信門檻 = 50 conversions" from scratch and repeats the mistake. The record
is the vaccine.

| ADR | Governed |
| --- | --- |
| 0006 | 配碼校驗不鎖開跑 |
| 0007 | 凍結猜消費者反應的拒絕理由 (`app/ads/fingerprint.py`) |
| 0008 | 圖片不進系統、歸因收在主題層 (`app/ads/creative.py`) |
| 0010 | 排期曲線接受學習期重置 |
| 0011 | 下期建議最小樣本數＋檔期情境加權 (`app/ads/nextcycle.py`) |
| 0012 | 規則有效期（**只有這半**——prompt 上限那半仍在force，見下方註） |
| 0014 | 節日相關性業種比對 |
| 0015 | 「這期跳過」只留脈絡 |
| 0016 | QA 五項自行確認、不擋人 (`app/ads/meta_api.py`) |
| 0022 | 現在結算與匯入撤銷 |
| 0025 | 「停掉」下沉到廣告層 |
| 0026 | 一條學習＝一個結論＋一個適用範圍 |

Their subject matter is not gone — it moves out of Python and into `rules.md` and the ad
department's task files, where the user can read a threshold, disagree with it, and change it
in five seconds instead of editing code and waiting for review. That relocation is the whole
argument of ADR 0028.

Three other ADRs are marked but **not** retired:

- **0012** (rule expiry + prompt cap) — _added 2026-09-07, after the row above was read as a full
  retirement._ Only the expiry half went with the module: `app/brand_intelligence/rule_lifecycle.py`
  and the `rule_expiry` card no longer exist, and nothing sweeps a rule back to 待確認. **The prompt
  cap is live** — `app/llm/context_compiler.py:_select_rules_for_prompt` still reads the
  `rule_prompt_cap.max_active_rules` card. ADR 0012 stays in `docs/adr/` with `status: in-force`
  and carries its own 2026-09-02 half-live/half-gone note; do not delete `_select_rules_for_prompt`
  on the strength of this table's row.
- **0004** (drop named authorization) — its stated premise is "系統是單機單人，永遠只有當事人
  操作". ADR 0027 and `CLAUDE.md` #1 overturned that premise. `authorized_by` auto-filled with
  a fixed value is an audit gap under multi-tenancy. Unresolved; not caused by this slice.
- **0005** (LLM web search) — the mechanism in `app/llm/providers.py` survives; its only two
  call sites (`app/ads/plan.py`, `app/ads/creative.py`) are deleted with the module.
