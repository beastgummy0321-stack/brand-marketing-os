# 07-2 部署前（選平台後）

Status: blocked-on-platform。
關聯：Hey API TS client、Sentry、staging、CD（單一 job `supabase db push`）。

- **部署映像檔要有 IANA 時區資料庫**：`today_for_org()` 靠 `zoneinfo`；Debian 系內建，Alpine 沒有——
  沒有就開機第一次算日期時大聲炸掉，這是刻意的，不要安靜退回 UTC。
- Sentry／staging／CD 三件都要先知道部署在哪裡才寫得出來。

2026-09-05：原本掛在這張的前半（pydantic-settings 收環境變數）已升成票
`docs/issues/deploy/02-env-flag-and-settings.md`，連同 `issue-is-local-env-flag.md`
一起收走（ADR 0062）。那半不必等平台，這半要等。
