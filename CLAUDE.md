# CLAUDE.md — Brand Marketing OS

Claude 與 Codex 共用本指引。Harness 依任務選入口：`dig` 討論、`carve` 規劃、`crank` 執行已授權佇列。
小而明確的局部修復可直接處理；需要隔離、相依排程或續接的功能才建立佇列。最新使用者指示決定範圍。

## 全專案設計原則

- **模組如集裝箱**：內部實作封裝，跨模組只走明確、穩定的公開契約，讓替換與故障影響限於所屬範圍。沿用既有接口慣例；邊界、依賴與資料所有權以 `ARCHITECTURE.md` §1–3 為準，不另建一套規則或通用框架。
- **程式整理，LLM 判斷**：整理、計算、篩選與欄位映射由程式完成；LLM 僅接收必要且已整理的資料，執行需要模型的判斷、決策與既有創作生成。沿用 LLM gateway，控制 token／費用；輸入保留來源、未知與必要上下文，輸出經契約及事實檢查，避免上下文遺失或幻覺直接成為產品事實。必要時才拆多 agent，分工與交接仍受上述限制。
- **多平台兼容（已確認）**：多廣告平台、多帳號／店鋪及購物平台是必要架構需求。內部投放計畫與平台原生物件分離；共用核心不得寫死 Meta 的層級、預算位置或成效口徑，平台差異由能力接口與 adapter 承接。購物平台範圍為站內廣告、商品、訂單、退款與成效分析，不含上架改價、庫存及出貨管理。既有單平台限制是待改善現況，不得作為縮減需求的理由；未支援能力如實呈現。共用流程同樣保持品牌、產業與使用者中立，未確認假設不得固化。
- **先根因、後表象**：表象是「哪裡錯了」；根因是「什麼條件讓這一類錯必然發生」。除錯、審核、安排工作流程時先追因果鏈（表象 → 為何發生 → 上游哪個決定或缺口 → 流程為何沒自然擋住），回報先講根因與它還會生出哪些同類錯，表象只當證據；修正對準讓條件消失的最小系統性改動，不逐個修補表象。同類錯第二次出現＝上次沒修到根因。
- **最小必要變更**：沿用既有編寫方式與業務邏輯，只改本次授權範圍；發現 Bug 依影響處理，遇到決策分歧或偏離已確認結果先提出，不順手重構或擴張功能。執行與授權流程沿用 Harness。
- **三層介面、分期實作**：第一層為未來的 Full auto，由系統接管素材準備、投放等流程，待程式穩定後最後開發；目前只做第二層「新手逐步操作、可查看每一步」與第三層「同頁按項目展開進階參數」。一般層呈現必要摘要與下一步，複雜設定預設收合；進階層揭露可自訂參數。現階段不以簡化介面代替使用者核准，也不假裝已有全自動能力；細節依 `docs/design-system.md` §F12。
- **UIUX 驗收獨立於功能驗收（2026-09-20 裁決）**：功能測試通過不代表介面達標。任何前端工作先依預覽圖重做資訊層級與視覺配置，再接資料；不得沿用舊頁面加說明、狀態與表單充當改版，也不得用說明文字或新手指南代替設計。驗收標準與五問檢查依 `docs/design-system.md` §1.7，UI 票必附參考圖並以並排截圖對照作證據。切票：一個畫面一張票，`touch` 涵蓋該畫面的資料夾與相鄰測試；切票前逐欄核對參考圖上的欄位在 `/api` 回應裡存在，缺的先併成一張小後端票。票上的版面規格就是 HTML 原型本身（工人開瀏覽器看該畫面與其互動、狀態；2026-09-22 重申），截圖只是並排對照的左半邊，不另用文字轉述畫面；工人用真實形狀的測試資料開發，交件附「參考圖｜成品」並排圖，主導先比對、不像就退回。使用者只在整批合併後看一次並排頁，agent 中途不停下來等驗收。工人自查表與細則在 §1.7。

文件入口依需求選讀，不依序全讀：
- `ARCHITECTURE.md`：機器 manifest、模組邊界與所有權；§5／6／8 連到各領域唯一決策頁。
- `CONTEXT.md`：業務用詞；`docs/design-system.md`：UI 規則；`docs/verification.md`：檢查時機與環境。
- `.work/`：已規劃 Feature 與工作票；`.harness/`：本機執行狀態與暫存證據。
- `docs/backlog/`：未排入佇列的候選，只找與當前問題相關者；`docs/drills/README.md` 只在演練時讀。
- 既有 Campaign／自帶素材工程：先讀 `docs/architecture/ads.md` 的相關決策；僅在缺少原始需求或未實作範圍時讀 `docs/backlog/engineering-existing-campaigns-user-assets.md`。規劃自主行銷／大型重構時才讀 `docs/backlog/roadmap-autonomous-marketing-major-updates.md`，另用工作樹；文件不是實作授權。
- `docs/boot-autostart.md` 只在處理 Windows 登入自動啟動時讀。歷史 ADR、done 票與探測紀錄不是開工必讀。

## 階段收尾（dig／carve／crank 與直接修復共用）

只整理本次影響的文件；沒有持久決策或行為變更就不寫文件。討論限定唯讀時在回覆列結論，不能為收尾改檔。
- dig：需保存時更新現有候選／discovery；區分已確認、假設、待決，不另生會議摘要。
- carve：將定案放進所屬領域頁，Feature Decisions 只留共同約束與精確指路；證據放獨立 `# Evidence`，不要灌進 worker 上下文。僅在新增／搬移頁面時更新這份入口或架構索引。
- crank／直接修復：同步本次改動造成的現況與驗證限制；收尾只查修改的引用及其入站連結。定案已被吸收的候選合併或刪除前，保留仍未實作的範圍與唯一證據。未完成驗收的 Feature 不刪、不冒充結案。
一次整理即可；不為換階段重讀全库、另寫收尾報告、建立新看板或新審批。舊版由 Git 保存，不複製帶日期的現行規範。無關問題留待原有 backlog，不擴張本次工作。

## 資料狀態（正式發布時刪除本節）

系統**未發布**。`data/`、`backups/`、資料庫內容全為測試資料，可直接刪除重建，
本機重建不需再次確認，但要先確認目標仍是測試環境，遵守 worker touch 與共享 DB 的使用邊界；不能刪除其他任務的資料或證據。正式環境、對外操作與敏感資料仍受安全規則約束。

## 開場（每次 session）

1. 有收到 Harness SessionStart 狀態時，以它定位相關 Feature、工作票與未完成事項。
   未收到時，續接佇列先執行 `node "<已載入插件根目錄>/bin/harness.mjs" status`。
   嚴格唯讀且需要續接狀態時，只讀相關 Feature、工作票與 leases；CLI status 會寫 metrics。無關的問答、審查或直接小修跳過佇列狀態讀取。
   沒有 `.harness/` 時，只有建立佇列才初始化；討論與小修復不需要初始化。
2. 既存計畫與驗證紀錄是上下文，不是本次執行授權。判斷 Feature 是否完成時才檢查 `closed` 與人工驗收；佇列空不代表結案。
3. 只搜尋與本次議題相關的 backlog。已裁決但未實作的條目可沿用決定，不重開相同問題。

## 地標

- 技術棧：Python＋FastAPI＋Postgres（Supabase：Postgres／Auth／Storage／Vault）；原生 SQL 不用 ORM；
  背景工作走 procrastinate，worker 是獨立行程；前端 React＋Vite（`frontend/`，build 後掛 `/app`），
  後端只出 `/api` JSON。目前程式使用 Postgres；需要分支資訊時查 Git，不依分支名稱推測舊架構。
- ARCHITECTURE.md 的 `stack` 是 `python`（2026-09-10 裁決）：後端 `app/<模組>/` 是受管模組；
  前端邊界沿用 `frontend/.dependency-cruiser.cjs`（功能資料夾只准從 `index.ts` 進出），
  放在 verify 指令裡跑，不另立 harness 模組。
- 後端模組：`app/<模組>/`＋自己的 migrations，不碰別人的表；分層方向與跨層 SQL 的機器檢查在
  `app/tests/test_architecture_boundaries.py`。
- `app/methodology/` 與 `app/departments/` 是 prompt 程式零件。已授權的行為修改可直接處理並驗證；未授權的產品決策改變才需確認。
- Harness 執行路徑以主機載入的技能位置為準；修改插件前查目前 marketplace 指向的來源。
  Codex 本機安裝與 Claude 安裝分別更新；發布依使用者明確授權執行。Push 統一由使用者手動執行，agent／plugin 不執行、不建立自動推送 hook。

## 指令

- 啟動：`啟動行銷系統.bat` → http://localhost:8710/ ；本機開發先 `supabase start`。開機自動啟動見 `docs/boot-autostart.md`。
- 裝依賴：`uv sync --frozen`（不用 pip）。金鑰在 `.env`；`BRAND_OS_LLM_PROVIDER=codex_cli`＝LLM 走本機 codex，不產生帳單；
  跑 pytest 前 unset 它（它會蓋掉測試的假供應商）。
- bash 跑 docker／supabase 前：`export PATH="/c/Users/User/AppData/Local/Programs/DockerDesktop/resources/bin:/c/Users/User/scoop/shims:$PATH"`
- 測試帳號 `123@example.com`／`123456`（`supabase/seed.sql`，組織 `org_bughunt`、品牌 `brd_bughunt`）——
  **唯一活得過 `supabase db reset` 的帳號**；reset 洗掉 seed 以外的一切。
  直接打 API 可自簽 HS256 JWT（`IDENTITY_ALLOW_HS256=1`，密鑰＝`SUPABASE_JWT_SECRET`）。
- 驗證依 `docs/verification.md` 選時機；共用命令在 ARCHITECTURE frontmatter，工作票只補受影響測試，不重複全域閘門。
- CI：`.github/workflows/ci.yml`，push／PR 到 `saas`／`master` 都跑。

## 鐵律（只列這個專案特有的；通用的在 plugin）

- **不要求、不提醒使用者實機投放 Meta**（2026-09-07 裁決、2026-09-08 重申加嚴）：提示詞、素材產出、廣告排程完全落地前，
  任何 issue、文件、回報都不寫「要看到真結果得讓活動跑」；帳戶資料的狀態只當事實記錄。驗收用測試資料證明分支，真資料只證明管線會動。
- 實機驗收要在**重啟過的後端**上做——閘門看不到「跑的是舊程式」。
- Migration：`supabase/migrations/<timestamp>_<模組>_<desc>.sql`，只能 CREATE 自己模組前綴的表；已套用的檔不改，修正開新檔；
  重指向一張表前 `grep -rn "REFERENCES <table>" supabase/migrations/`。
- 對外發布、花錢、正式資料變動：先說後果並取得該動作授權；已有明確授權不重問。Git push 依上方手動推送規則。

## 對使用者說話

繁體中文、白話；使用者非工程背景，術語第一次出現附一句比喻；一次一題、給選項標推薦；時間講具體。耗時以 `.harness/runtime/metrics.jsonl` 實測為準，不憑印象估。背景通知醒來時只回一行，除非需要使用者裁決、有票合併完成或出現阻塞。
