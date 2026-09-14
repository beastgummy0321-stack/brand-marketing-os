# e2e 後端吃 .env 的 codex_cli 真模型（逾時已由 F06-I00 放寬；根治未做）

Status: 2026-09-14。「把 `width-overflow.spec.ts:122`／`:128` 的等待拉長」已被 F06-I00 消化（各 60 秒、整支測試
180 秒），這條只剩根治與判讀方法。

事實：
- `frontend/playwright.config.ts` 的 webServer 起 8720 後端時不覆寫 `BRAND_OS_LLM_PROVIDER`，所以 `:122`（解析需求）
  與 `:128`（產生策略）是真的本機 codex 在跑。實測 `ads_brief_parse` 14.8–15.1 秒、`ads_strategy` 15.7 秒；
  原本 15 秒／30 秒的預算讓 `:122` 幾乎必紅，不是閃紅。
- 上游塞車是另一種紅：07:33～07:51 UTC 每筆 `llm_task`（codex_cli）都失敗，error＝「Selected model is at capacity」。
  判讀 e2e 紅燈前先看 `select started_at, task_type, status, error from llm_task order by started_at desc limit 10`；
  塞車只能重跑，放寬逾時救不了。
- `BRAND_OS_LLM_PROVIDER=fake` 不成立：`app/llm/providers.py:40` 只認 `codex_cli`；`FakeProvider` 固定回
  「（假回覆）測試用輸出」，不是合法的 brief／strategy JSON，換上去 e2e 會穩定紅。

未裁決的根治做法：給 e2e 一個照 task_type 回合法 JSON 的腳本化提供者，或 e2e 改走種子 Campaign 跳過兩次模型呼叫。
兩者都會讓 e2e 不再受上游塞車影響，也能把 F06-I00 的 60 秒收回來。
