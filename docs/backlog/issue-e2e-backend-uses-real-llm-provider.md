# e2e 後端吃 .env 的 codex_cli 真模型，兩處 toHaveURL 隨延遲閃紅

Status: 2026-09-14 F05 /crank 三次撞到（I08 finish、I10 工人自跑、I14 merge smoke），每次重跑即綠、每次代價約 15 分鐘。

事實：`frontend/playwright.config.ts` 的 webServer 起 8720 後端時不覆寫 `BRAND_OS_LLM_PROVIDER`，所以
`width-overflow.spec.ts:122`（建 Campaign 後等 `/ads/new/<id>`，15 秒）與 `:128`（等 `?tab=strategy`，30 秒）
是真的本機 codex 在解析／生成，慢的時候就逾時。`app/llm/providers.py:730` 已有 `name = "fake"` 的提供者。

做法（未裁決）：webServer 的 `env` 設 `BRAND_OS_LLM_PROVIDER=fake`（e2e 看的是版面與流程，不是模型內容），
或把那兩處 timeout 拉到 90 秒。前者乾淨、後者一行。
