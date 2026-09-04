# 07-2 部署前（選平台後）

Status: blocked-on-platform。
關聯：Hey API TS client、Sentry、staging、CD（單一 job `supabase db push`）。

- **pydantic-settings 收環境變數**：現在 19 個地方各自讀、8 個不同的鍵，缺了或打錯字會安靜地用預設值
  繼續跑。它真正值錢的時刻就是第一次部署——開機當場大聲失敗，好過上線後某個功能莫名不動。
- **部署映像檔要有 IANA 時區資料庫**：`today_for_org()` 靠 `zoneinfo`；Debian 系內建，Alpine 沒有——
  沒有就開機第一次算日期時大聲炸掉，這是刻意的，不要安靜退回 UTC。
- 順手收 `issue-is-local-env-flag.md` 那顆「正式環境」變數。
