# `BRAND_OS_LLM_PROVIDER=codex_cli` 在正式環境是合法的，但那條線在雲端不存在

Status: before-first-deploy——2026-09-05 開票 02 時發現，那張票刻意不收（它管的是「環境叫什麼名字」，
這條是「哪個供應商」，混在一起會讓那張票的 done-check 變成兩件事）。

成因：`app/llm/providers.py:37-43` 只比對 `BRAND_OS_LLM_PROVIDER == "codex_cli"`，不看環境；
`app/main.py:277` 依它換供應商。這顆變數存在的理由是「開發期不打 API 帳單」（ADR 0032），
本機有 codex CLI 這支程式，雲端主機沒有。

影響：`.env` 帶著這一行部署上去，每一次 AI 呼叫都會去執行一支不存在的指令。不是安靜算錯錢，
是全部 AI 功能安靜地壞掉——而帳面上看起來「沒有花錢」。

`file:line`：`app/llm/providers.py:37-43`、`app/main.py:277`。

做法（等 02 落地之後，一行的事）：`app/core/config.py` 的表加一條——`BRAND_OS_LLM_PROVIDER`
在 `staging`／`production` 只允許空值或平台供應商，`codex_cli` 屬 `local` 限定。
