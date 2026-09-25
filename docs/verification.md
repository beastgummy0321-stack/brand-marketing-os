# 驗證：依變更與階段執行

命令唯一出處是 [ARCHITECTURE.md](../ARCHITECTURE.md) 的 `verify` 與 `checker`；CI 保留 [.github/workflows/ci.yml](../.github/workflows/ci.yml) 的必要檢查。工作票只補本次行為測試，不複製共用命令。

| 情境 | 必要驗證 |
|---|---|
| 一般工程文件 | 檢查修改的引用、規則一致性與 diff；有 frontmatter 則驗證其 schema |
| 小型直接修復 | 受影響的測試與型別／邊界檢查；碰前端建置才 build，碰啟動／跨層流程才 e2e |
| 佇列 issue | 開發中跑定位問題所需測試；交給 `finish` 統一跑票上 verify、checker 及適用的 typecheck／build；僅純後端測試／程式提示詞可用 manifest 的 issue profile，介面變更與未匹配範圍維持全套；不要交件前再完整跑一遍 |
| issue merge | checker 與 smoke 驗證合併後的樹，不能沿用合併前結果冒充 |
| Feature integration | 全域型別、build、完整後端／前端測試、smoke，再加未涵蓋的 Feature 專屬驗證；完整套件已含的子集不再列；`typecheck_before_test` 不重跑完整 Vitest 已包含的前端邊界測試 |
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
- `test_real_db_schema_drift.py` 固定比較該連線資料庫的 `public` 與全新 migration 結果；僅改 `search_path` 不能隔離這個基準。共享 `public` 尚未套本分支 migration 時，完整整合使用另建的本機測試 database，先在其 `public` 套 migration／seed，再以 `DATABASE_URL` 指向它。保留原斷言，不跳過差異或修改共享資料庫來換取通過；Auth／Vault 必須保留真實結構與擴充能力。

## e2e 的能力邊界

`npm run e2e` 會 build，再由 Playwright 啟動 8720 後端。若本次 Harness integration 已成功 build，`verify.smoke_after_build` 使用同一 checkout 的 `npx playwright test`，避免第二次 build；不能跨樹或沿用未知的 dist。
[playwright.config.ts](../frontend/playwright.config.ts) 用 `scripted` 供應商與 `memory` queue，僅允許 local。未知 task type 會失敗；背景工作不執行。需背景結果的測試應選擇可覆蓋該行為的整合測試或授權的獨立測試環境，不能把等待逾時當驗收。`ads-cold-start.spec.ts` 需要素材預覽，改在測試裡直接呼叫 worker 的 `process_preview`（CI 已有 FFmpeg）。
新的 scripted reply 必須由所屬模組測試約束形狀；涉及 legacy seam 的票仍需 `legacy_migration` 與邊界審查。保留租戶隔離、憑證保護與費用限制。

### F13 的隔離完整流程

人工逐步驗收請依 [F13 驗收手冊：既有活動、自帶素材與手動上架](acceptance/f13-existing-campaigns-user-assets.md)。

真帳號驗收的 server 與 worker 必須使用同一 checkout 與本機設定，且 `BRAND_OS_JOB_QUEUE=postgres`；memory queue 只適合隔離 smoke，會令跨程序同步停在首段。真實讀取、模型回覆與平台寫入的驗證範圍分開記錄。

`uv run python scripts/verify_existing_campaigns_assets.py --isolated --timeout 180`
讀本 checkout 的本機 `.env`（也可明確指定 `--env-file`），建立自己專用的 schema／組織／品牌，
啟動 8731 起的獨立服務。它只讀取既存 seed 登入者的 Auth 身分，不 reset 或建立共享 Auth fixture。
真 HTTP、資料庫、Storage、FFmpeg、gateway 與同步／預覽／補文案 handlers 均實際執行；
平台 reader 與模型 provider 僅在測試程序注入，外部非本機傳輸一律拒絕，未測試真模型或平台寫入。
執行預算包括媒體建立、DDL、啟動等待與 HTTP；清理另有有界的程序／Storage／DB 等待，
正常與失敗路徑皆產生 `cleanup.json`。重啟前保留實際 queued 工作，重啟後由真 dispatcher 續跑，
並核對原檔 bytes 不變。stdout 提供本機證據目錄；`runtime-result.json` 與清理結果必須一起檢查。

不要把舊服務、fixture 回應或佇列 done 當成真帳號能力及人工驗收；F13 與 F07 的未驗收項目分開保存。

## UI 與視覺

- 新畫面、版面或共用元件變更：依 [設計系統](design-system.md) 與該頁參考圖比較實際截圖。局部文案修正只驗證受影響位置，不強制啟動設計技能或完整全站巡覽。
- 在本次 worktree 的新建置上，以隔離測試埠（8731＋票號，例如 I03 用 8734；8710 是使用者的、8720 只給 harness merge／integrate）與測試帳號登入。驗證登入流程時不能靠偽造 token 略過；其他測試可使用隔離的測試登入狀態，不保存憑證到 repo。
- 版面檢查 1024、1920 與受影響的 loading／empty／error 狀態；共用 kit／shell 變更才擴到經營概況、投放中心、品牌智庫的 empty／normal／heavy。已有同樹有效截圖不再重拍。
- 使用主機可用的瀏覽器工具；需暫存腳本或截圖時放 repo 外的任務暫存目錄，遵守 scope，結束關閉自己啟動的瀏覽器／伺服器。報告程式版本、頁面狀態與證據路徑。工具失敗如實報告，不能宣稱已驗收。
- `review: planner` 的風險審查保留；一般視覺比較可由當前 agent 完成。只有主觀品質判斷或真正人工操作才交使用者，不重問已授權的局部修正。


### F15 的 A／B／C／D 隔離驗收

`uv run python scripts/verify_ads_cycle.py --isolated --phase D --timeout 240`
沿用 F13 fixture 基礎，但限定專用 `f15_validation_*` database。A／B／C 可由 `--phase`
分別執行核准月額、檢討文案及素材交接；D 使用真 Postgres 佇列、獨立 Web 與
`app.worker.main`，外部 reader／模型仍是替身且只允許本機傳輸。

D 在來源第二頁、模型已保存未掛回、模型呼叫中、檢討已保存未入佇列等真執行邊界中斷
自己啟動的程序，再由正式恢復入口處理；Windows 以實際 worker PID 與啟動鍵核對，
不得只停止 venv launcher 就宣稱 worker 中斷。檢查 `source-recovery.json`、
`review-recovery.json`、第二輪證據、`runtime-result.json` 與 `cleanup.json`；
`ok` 只證明隔離流程，不代表真平台修改或真實營收改善。

這兩支 runner 只做 HTTP／資料庫層驗收，不再附瀏覽器 spec（2026-09-26 退役）；冷啟動的畫面流程由
一般 `npm run e2e` 的 `ads-cold-start.spec.ts` 自建帳號資料跑。真 Meta 唯讀探測另列
實際取得欄位與缺漏；不得把替身設定讀回、使用者自述或檢討完成當作真實平台變更證據。
