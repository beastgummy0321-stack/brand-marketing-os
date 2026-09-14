# e2e 後端吃 .env 的 codex_cli 真模型，兩處 toHaveURL 隨延遲閃紅

Status: 2026-09-14 F05 /crank 三次撞到（I08 finish、I10 工人自跑、I14 merge smoke），每次重跑即綠、每次代價約 15 分鐘。

事實：`frontend/playwright.config.ts` 的 webServer 起 8720 後端時不覆寫 `BRAND_OS_LLM_PROVIDER`，所以
`width-overflow.spec.ts:122`（建 Campaign 後等 `/ads/new/<id>`，15 秒）與 `:128`（等 `?tab=strategy`，30 秒）
是真的本機 codex 在解析／生成，慢的時候就逾時。`app/llm/providers.py:730` 已有 `name = "fake"` 的提供者。

2026-09-14 F06 補充（實測，推翻上面的一行做法）：
- 另一種紅：不是慢，是上游塞車。07:33～07:37 UTC 每筆 `llm_task`（codex_cli）都失敗，error＝
  「Selected model is at capacity」，e2e 在 `:122`／`:128` 連紅四次；07:39 恢復。判讀 e2e 紅燈前先看
  `select started_at, task_type, status, error from llm_task order by started_at desc limit 10`。
- `BRAND_OS_LLM_PROVIDER=fake` 不成立：`app/llm/providers.py:40` 只認 `codex_cli`，沒有 env 選得到的 fake；
  `FakeProvider` 固定回「（假回覆）測試用輸出」，不是合法的 brief／strategy JSON，換上去 e2e 會穩定紅。
  真要根治＝給 e2e 一個照 task_type 回合法 JSON 的腳本化提供者，或 e2e 改走種子 Campaign 跳過兩次模型呼叫。

做法（未裁決，原寫法）：webServer 的 `env` 設 `BRAND_OS_LLM_PROVIDER=fake`（e2e 看的是版面與流程，不是模型內容），
或把那兩處 timeout 拉到 90 秒。前者乾淨、後者一行。
