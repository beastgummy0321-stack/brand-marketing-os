"""app/intake/script.py — the brand-onboarding draft cost cap default.

F42-I14 removed the retired onboarding stage (scan impressions, AI Q&A, handoff prompt, paste
samples, system research); what stays is the default of the per-draft AI cost cap, read by
`app/core/settings.get_intake_budget_limit()` (the cap the prefill and 「自訂」 calls are checked
against, `state.would_exceed`).

Currency: US dollars, the same unit `app/llm/pricing.calculate_cost()` returns, compared directly
with no exchange rate (ticket M2: the screen prints 「US$」 so the cap is not read as NT$).
"""

DEFAULT_BUDGET = 30.00  # US$30
