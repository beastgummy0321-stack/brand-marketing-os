# 目標：上線／上雲前必還的帳

Status: 2026-09-05 那輪把原本十條平台無關的債全還了（`slice-01`～`slice-09 done`；教訓在 ADR 0061／0062／0063 與
契約頁 `core.md`／`meta.md`／`background.md`／`intake.md`，這裡不重抄）。還那十條時又量到五條新的，狀態各自寫在檔頭。
這些不擋本機閉環，但**第一次真的部署當天每一條都會咬人**，所以留著不刪。開工時把 issue 升票（改名 `NN-*.md` 填四欄）。

**A. 跟平台無關，現在就能做**

1. `issue-intake-error-shape-diverges.md` — before-cloud。
2. `issue-intake-pending-photos-dict.md` — before-cloud。
3. `issue-post-processing-failure-reads-as-done.md` — before-cloud；`app/intake` 與 `app/brand_web` 同病。
4. `issue-research-status-reads-done-while-queued.md` — before-cloud。
5. `issue-delete-seed-debug-account.md` — **部署前一天才做**：刪了之後本機就沒有活得過 reset 的帳號。

**B. 要先選平台**

6. `issue-07-2-settings-sentry-staging-cd.md` — Sentry／staging／CD（`supabase db push` 單一 job）＋映像檔帶 IANA 時區。
7. `issue-07-4-github-security-switches.md` — 要付 GitHub Pro 或把 repo 公開，是錢的決定。
8. `issue-ai-cost-reconciliation.md` — 要 Anthropic Admin API key；開始收費前對一次帳即可。

**不是債，只是住這裡**

- `issue-intake-scan-per-photo-progress.md` — decided-and-deferred（2026-09-05 使用者裁決不做，記著才不會被當成弄丟的功能）。
- `issue-meta-unknown-parent-id-fail-open.md` — known-residual（今天打不到；門檻是真的多了第二個呼叫端）。
- `issue-key-source-switch.md` — 里程碑之後的產品功能，跟「自帶金鑰」同一組所以放這。
