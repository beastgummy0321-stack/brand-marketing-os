# 切片看板（只放未開始＋進行中；完成即刪行，歷史＝git log）

排序＝執行順序。標「需批准」的票動工前先提計畫等批准；動到畫面先過畫面契約（草圖 → 後端 → 前端）。

## 里程碑（2026-08-29 排程模組併回 `saas` 後改寫）

第一段 $0——整套在本機 `supabase start` 跑通，用真品牌走完一條路：
**排程頁填表 → 出 N 個方案 → 選一個展開成三層活動樹 → 人照樹上的名稱在 Meta 後台自己建、
自己投放 → 名稱配對把成效綁回方案**。第二段才推免費層雲端。

2026-08-29 併回 `saas` 當天實測（LLM 走本機 codex CLI＝$0；Meta 只讀不寫；沒有送出任何廣告）：
表單、三個方案、金額分配、三層活動樹、每日花費拉取（BP AD 真實數字）、配對失敗訊息，
畫面上全部跑通。缺的是**素材**與**配對成功**那半條，見第 ⑧ 片。

原本寫的是「用真品牌跑一期廣告閉環」。**那個閉環就是 `app/ads/`**，已於 2026-08-29 整個
刪除（21,595 行；要回頭看用 tag `v0.2-ads-last`）。回收成效（CSV 匯入）、覆盤、下一期都
**不在 v1**（`HANDOFF-shell-slice.md` §3.1，該檔已於本次併入後刪除，內容進 git log 與本看板）。

## 第 ⑧ 片：排程與外殼（`.scratch/schedule-module/issues/` 12 張票，完成 11 張半）

- [ ] 11 名稱配對剩下那半條：配對失敗訊息已上線；**綁定 platform id、綁定後顯示該活動的花費
      與 ROAS 還沒做**。要一個真的在 Meta 手動建好、名稱完全相符的活動才測得到（建成 PAUSED
      不花錢）
- [ ] 素材模組：`app/departments/` 底下只有 `ads/`，creative 一行都還沒寫——里程碑的另一半
- [ ] `approval` 表＋預算核准閘門（約 20 行，外殼唯一會拒絕的地方）：現在錢由程式算、畫面
      顯示，但沒有「人按核准」這一關
- [ ] ADR 0032 的第四種 Provider：`codex_cli` 已上線（`.env` 的 `BRAND_OS_LLM_PROVIDER`），
      claude CLI 那一種還沒

## 第 ④ 片：設定與憑證（需批准：schema）

- [ ] 04-1b pydantic-settings 收環境變數＋組織時區（`org_timezone`，IANA，預設 Asia/Taipei，只改排程面的「今天」）＋`llm_task.methodology_hash`（動 schema，一個欄位）
- [ ] 04-2 剩下的一半：自帶金鑰（`own`）的 AI 金鑰進 Vault＋設定頁切換金鑰來源。Meta 憑證進 Vault、組織層「已連接帳號」→ 品牌綁定**已完成**（`.scratch/schedule-module/issues/04`）

## 第 ⑤ 片：背景工作

- [ ] 05-1 procrastinate 的 `enqueue／status／cancel` 契約、job 註冊表。**安裝與 worker 進場點已完成**（票 01＋ADR 0038／0039：自己的 schema、worker 是 uvicorn 行程裡的一個 asyncio task，由 FastAPI `lifespan` 開關）。目前實際跑在上面的只有 Meta 每日花費拉取；`_progress_state`（brand_web 的 library／products 各一份）仍在待搬清單裡

## 第 ⑥ 片：素材

- [ ] 06-1 Supabase Storage 每組織一 bucket（雲端版的素材落腳處）；`creative_asset_root` 退役

## 第 ⑦ 片：收尾

- [ ] 07-1 閘門收尾：前端 depcruise 擋 supabase-js 只在登入模組（**Playwright 那一半已於 2026-08-29 完成**，見 `frontend/e2e/smoke.spec.ts`，`cd frontend && npm run e2e` 一行跑完）
- [ ] 07-2 部署前（選平台後）：Hey API TS client、Sentry、staging、CD（單一 job `supabase db push`）

## 小債（順手做，不排優先）

- [ ] **左側導覽有四條死連結**（投放與成效／累積智慧／素材工作檯／資料上線）：外殼切片刪掉那 8 條路由，導覽沒跟著刪，點下去整頁空白（2026-08-29 瀏覽器實測）。**這是使用者看得到的謊**，且 `HANDOFF-shell-slice.md` §3.7 寫的是「刪掉，不做轉址」
- [ ] **選了產品，產品名稱卻沒進 prompt**：`context_compiler.compile()` 只吐「已確認的事實／規則／宣稱／典型客人」，`_plan_params_text()` 不列產品名與售價。晨光咖啡 0 筆 confirmed fact ⇒ 品牌上下文長度為 0，方案只能靠「促銷或重點」那一欄的字（2026-08-29 實測）
- [ ] 排程表單的「行銷目標」下拉每次回到第一個選項（認知），不記得上次送出的目標
- [ ] `app/core/rule_cards.py` 8 張規則卡有 6 張失效（`budget_structure`／`sample_size`／`ad_creative_fatigue`／`pacing`／`health_lights`／`autonomy`），設定頁照樣顯示、照樣可以調，但調了不影響任何東西——**這是使用者看得到的謊**（明細見 `docs/tech-debt.md` 第〇節）
- [ ] **上雲前必還（ADR 0039）** 每日 Meta 花費拉取的 worker 跑在網站行程裡：網站沒開就不拉，那天沒有數字（handler 可重跑，但沒人叫它就沒人補；手動補：`uv run python -m app.meta.daily_pull`）；cron `0 3 * * *` 是機器本地時間，沒有時區處理（等 04-1b 的 `org_timezone`）。上雲時 worker 要拆成自己的行程
- [ ] GitHub 四個安全開關（secret scanning／push protection／CodeQL／branch protection）需 GitHub Pro 或公開 repo——**等使用者決定**要不要付費；未付費前 CI 綠不擋合併，靠人工
- [ ] Dependabot #1（high）：前端間接依賴 `nanoid`（size=0 無限迴圈，開發工具鏈才用到）——動前端時 `npm audit fix` 順手收
- [ ] **上雲前必還（2026-08-28 使用者裁決：本機單人階段不修）** 邀請連結是「持有即可用」：`app/identity/routes.py` accept_invite 不比對 invite.email 與登入者 email；且 `AcceptInvitePage` 一掛載就自動接受，沒有確認步驟（03-3 審查 note 5）
- [ ] `pendingPath`（登入後導回原路徑）沒有時效也不會在登出時清掉：同一分頁先冷開邀請連結、之後做別的登入，會被靜默導回舊邀請頁（03-3 審查 note 4）
- [ ] 兩個繞過每月花費閘門的既有路徑（04-1a 審查 note）：`app/main.py` 設定頁「測試連線」（1 token 探測）、`app/intake/card_test.py` CLI 診斷工具（HTTP 碰不到）。風險小，但閘門既然蓋好了應該補齊
- [ ] `resolve_ai_credentials()` 的「DB 值打錯字→當 platform 處理」分支沒有測試覆蓋（04-1a 審查 note）
- [ ] 用自己金鑰（`own`）的組織看不到「調整月上限」欄位，切回 `platform` 時不好調——04-2 剩下那一半開放切換來源時一併處理（04-1a 審查 note）
- [ ] AI 成本對帳：`llm_task.cost` 是我們自己用 `app/llm/pricing.py` 算的**估算值**，不是 Anthropic 實際帳單。官方有 `/v1/organizations/cost_report`（按 workspace／api_key 分組，約 5 分鐘延遲，需 Admin API key）——上雲收費前要拿它跟自己的估算對一次帳，否則「每月上限」擋的是估算不是真錢（2026-08-28 查證）
- [ ] 404 信封兩種格式並存：`require_brand` 走 `NotFoundKind` 吐 `{"detail": …}`，`web.NotFound` 走 `handle_api_error` 吐 `{"error": {"code", "message"}}`（03-1 r1 審查 note 2）——第 ⑦ 片統一信封時一併收
- [ ] `app/tests/test_settings_api.py` 一條測試寫死 Windows 磁碟機路徑，非 Windows 跳過（`skipUnless`）；應改成跨平台斷言後拿掉 skip
- [ ] 變異度（同一份輸入跑 N 次結果差多少）仍未量測：探針在 `D:\0UserProfile\Desktop\MarketingOS Shell\variance-probe\`，從沒跑過。排程會做即時網路查詢，兩次跑本來就看到不同素材，重試預算現在是猜的

## 里程碑之後（上雲後才動）

- [ ] U1 新手五鐵則落地：全站術語大掃除＋禁用詞機器閘門＋步驟指示常駐（契約鐵則 11–12 驗收）

2026-08-29：V1-02（每日預算對帳）、M1-01（Meta MCP 一鍵建）、M1-02（同意即執行）、
M1-03（放手檔執行器）、P1（成效回流接通）五張隨 `app/ads/` 一起死——它們全部建立在檔期、
成效快照、切角歸因這些已經不存在的概念上。要回頭看內容：`git show v0.2-ads-last:BOARD.md`。
