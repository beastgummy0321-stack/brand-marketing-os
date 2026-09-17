# 驗證：依變更與階段執行

命令唯一出處是 [ARCHITECTURE.md](../ARCHITECTURE.md) 的 `verify` 與 `checker`；CI 保留 [.github/workflows/ci.yml](../.github/workflows/ci.yml) 的必要檢查。工作票只補本次行為測試，不複製共用命令。

| 情境 | 必要驗證 |
|---|---|
| 一般工程文件 | 檢查修改的引用、規則一致性與 diff；有 frontmatter 則驗證其 schema |
| 小型直接修復 | 受影響的測試與型別／邊界檢查；碰前端建置才 build，碰啟動／跨層流程才 e2e |
| 佇列 issue | 開發中跑定位問題所需測試；交給 `finish` 統一跑票上 verify、checker、typecheck、build；不要交件前再完整跑一遍 |
| issue merge | checker 與 smoke 驗證合併後的樹，不能沿用合併前結果冒充 |
| Feature integration | 全域型別、build、完整後端／前端測試、smoke，再加未涵蓋的 Feature 專屬驗證；完整套件已含的子集不再列 |
| schema／migration | 受影響測試加 `test_org_isolation_all_tables.py`、`test_brand_isolation_all_tables.py`、`test_architecture_boundaries.py`；完整後端套件已包含時不另跑 |

通過後只因相關程式、命令、依賴、環境變更或新失敗證據重跑。相同樹、相同環境的證據可共用；不要以換階段為理由人工重複檢查。Harness 的 merge/final integration 仍驗證各自的合併樹。
整合失敗但程式與環境未變時，可用 `harness integrate feature <id> --resume` 沿用一小時內通過的 machine 階段；checker、smoke、runtime 仍執行。`verify.build_outputs` 指定 `frontend/dist`，產物缺失或變更就重跑 build 與後續階段。重新安裝依賴、重設 DB／服務或無法確認環境時，使用不帶 `--resume` 的完整整合。部分檢查點不能用來結案。
`app/methodology/**/*.md`、`app/departments/**/*.md` 是程式提示詞，修改要跑對應行為測試，不適用文件免測。新增或實質修改安全／邊界檢查時，用代表性違規證明會失敗；mutation testing 只用於關鍵邏輯或測試敏感度存疑處，不要求每條 Done 各做一次破壞實驗。

## 本機環境

- `uv sync --frozen`；pytest 前移除 shell 的 `BRAND_OS_LLM_PROVIDER=codex_cli`，避免覆蓋測試假供應商。
- 測試 schema DDL 若遇到 PostgreSQL `DeadlockDetected`，只重試一次完整、已回滾的批次；第二次 deadlock 與其他 SQL 錯誤照常失敗。鎖循環／重試上限回歸見 `app/tests/test_schema_ddl.py`，不序列化測試本體。
- 本機完整後端套件使用 `-n 4 --dist loadfile`：2026-09-17 F09 整合時 8 個程序加既有服務耗盡 Postgres 連線並逾時，因此降低本機平行數；測試案例與斷言不變。20 核主機的 auto 也曾耗盡 100 條連線。loadfile 維持各測試檔的 DB/schema 隔離，不改 CI 配置。
- `supabase start`；migration 只在授權且確認共享 DB 沒有其他工作依赖時套用一次，放 `privileged`，不放會重跑的 verify。`supabase db reset` 會刪除 seed 外資料與帳號；本機測試資料可重建不代表 worker 可越過 touch 或干擾別人的測試。
- seed 登入資訊與啟動方式見 [CLAUDE.md](../CLAUDE.md)。長駐 8710 不保證是本次程式，實機驗收須重啟對應後端。

## e2e 的能力邊界

`npm run e2e` 會 build，再由 Playwright 啟動 8720 後端。若本次 Harness integration 已成功 build，`verify.smoke_after_build` 使用同一 checkout 的 `npx playwright test`，避免第二次 build；不能跨樹或沿用未知的 dist。
[playwright.config.ts](../frontend/playwright.config.ts) 用 `scripted` 供應商與 `memory` queue，僅允許 local。未知 task type 會失敗；背景工作不執行。需背景結果的測試應選擇可覆蓋該行為的整合測試或授權的獨立測試環境，不能把等待逾時當驗收。
新的 scripted reply 必須由所屬模組測試約束形狀；涉及 legacy seam 的票仍需 `legacy_migration` 與邊界審查。保留租戶隔離、憑證保護與費用限制。

## UI 與視覺

- 新畫面、版面或共用元件變更：依 [設計系統](design-system.md) 與該頁參考圖比較實際截圖。局部文案修正只驗證受影響位置，不強制啟動設計技能或完整全站巡覽。
- 在本次 worktree 的新建置上，以隔離測試埠（8731 起，避開 8710/8720）與測試帳號登入。驗證登入流程時不能靠偽造 token 略過；其他測試可使用隔離的測試登入狀態，不保存憑證到 repo。
- 版面檢查 1024、1920 與受影響的 loading／empty／error 狀態；共用 kit／shell 變更才擴到經營概況、投放中心、品牌智庫的 empty／normal／heavy。已有同樹有效截圖不再重拍。
- 使用主機可用的瀏覽器工具；需暫存腳本或截圖時放 repo 外的任務暫存目錄，遵守 scope，結束關閉自己啟動的瀏覽器／伺服器。報告程式版本、頁面狀態與證據路徑。工具失敗如實報告，不能宣稱已驗收。
- `review: planner` 的風險審查保留；一般視覺比較可由當前 agent 完成。只有主觀品質判斷或真正人工操作才交使用者，不重問已授權的局部修正。
