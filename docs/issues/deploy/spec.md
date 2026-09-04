# 目標：上線／上雲前必還的帳

Status: 卡點——**還沒選部署平台**。2026-09-04 使用者裁決「不用上雲沒關係」，這一輪不做。
全文出處：`BOARD.md` @ commit `6574191`。

這些不擋本機閉環，但**第一次真的部署當天每一條都會咬人**，所以留著不刪。選定平台那天，
把這個資料夾的 issue 逐一升票（改名 `NN-*.md` 填四欄）。

順序（咬人的先）：
1. `issue-delete-seed-debug-account.md` — 進了版控的已知帳密。
2. `issue-invite-link-bearer.md` — 持有即可用。
3. `issue-is-local-env-flag.md` — 自架同機拓撲會被判本機放行；空白屬 07-2。
4. `issue-07-2-settings-sentry-staging-cd.md` — 環境變數收攏＋時區資料庫＋Sentry／staging／CD。
5. `issue-daily-pull-worker-own-process.md` — ADR 0039 欠的。
6. `issue-ai-cost-reconciliation.md` — 上雲收費前對一次帳。
7. `issue-07-4-github-security-switches.md` — 需付費或公開 repo。
8. `issue-key-source-switch.md` — 「自帶金鑰」真的是在賣的方案時才做。
