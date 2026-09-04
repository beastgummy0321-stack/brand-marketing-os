# AI 成本對帳：`llm_task.cost` 是估算值，不是帳單

Status: before-charging。
關聯：`app/llm/pricing.py`；官方 `/v1/organizations/cost_report`（約 5 分鐘延遲，需 Admin API key）。

上雲收費前要拿官方報表跟自己的估算對一次帳，否則「每月上限」擋的是估算不是真錢。
