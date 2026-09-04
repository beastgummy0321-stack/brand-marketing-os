# 07-4 GitHub 四個安全開關

Status: deferred（2026-08-30 裁決：本機單人階段先不付費）。
關聯：secret scanning／push protection／CodeQL／branch protection；需 GitHub Pro 或公開 repo。

跟 Sentry／staging／CD 同一批再決定；在那之前 CI 綠不擋合併，靠人工。
Dependabot #1（`nanoid` 3.3.18）：`saas` 已是 3.3.18、`npm audit` 零漏洞；警示掃的是凍在 `v0.1-desktop` 的
`master`，會亮到 `saas` 併回 `master` 為止。不為了關警示單獨動凍結的 master。
