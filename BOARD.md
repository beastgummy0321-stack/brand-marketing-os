# 切片看板（只放未開始＋進行中；完成即刪行，歷史＝git log）

排序＝執行順序。分票唯一依據＝`docs/ui-migration-contract.md` v2（含隨批裁決）＋ ADR 0019。
標「需批准」的票動工前先提計畫等批准；動到畫面先過畫面契約（草圖 → 後端 → 前端）。

## 里程碑（2026-08-29 外殼切片後改寫）

第一段 $0——整套在本機 `supabase start` 跑通，用真品牌按兩顆按鈕：**`產生本期方案` →
`產生素材`，人自己把成品貼到 Meta 後台投放**；第二段才推免費層雲端。

原本寫的是「用真品牌跑一期廣告閉環」。**那個閉環就是 `app/ads/`**，已於 2026-08-29 整個
刪除（21,595 行；要回頭看用 tag `v0.2-ads-last`）——照原文寫是一個永遠到不了的目標。
回收成效（CSV 匯入）、覆盤、下一期都**不在 v1**（`HANDOFF-shell-slice.md` §3.1）。

## 第 ⑧ 片：外殼（**尚未切票**——等架構場次裁決「具體是哪兩頁」，`HANDOFF-shell-slice.md` §6.1）

已完成，不再列行（見 git log `58f493b`／`1d9ca48`／`1e247be`）：截肢 `app/ads/`、drop 44 張
廣告表、一條端到端煙霧測試、兩道「量」的機器閘門。

還沒切票、要等裁決的：兩顆按鈕、工單流頁＋儀表板頁（就是那兩頁）、`approval` 表、
把 agent CLI 當成 `Provider` 的第三四種實作（ADR 0032）、預算核准閘門。
**這一段是里程碑的主線**，⑤⑥⑦ 是它的周邊。

## 第 ④ 片：設定與憑證（需批准：schema）

- [ ] 04-1b pydantic-settings 收環境變數＋組織時區（`org_timezone`，IANA，預設 Asia/Taipei，只改排程面的「今天」）＋`llm_task.methodology_hash`（動 schema，一個欄位）
- [ ] 04-2 憑證進 Supabase Vault（本機已裝 0.3.1）＋「已連接帳號」（組織）→ 綁定（品牌）

## 第 ⑤ 片：背景工作

- [ ] 05-1 procrastinate：`enqueue／status／cancel` 契約、worker 行程。**契約活著、載荷換人**——原本要搬進來的 `_auto_sync_loop`／週引擎／`_immediate_sync_cache` 隨 `app/ads/` 一起刪了；現在它要背的是外殼的 agent 執行（一次 CLI 呼叫可能跑好幾分鐘，`HANDOFF-shell-slice.md` §6）。`_progress_state`（brand_web 的 library／products 各一份）仍在待搬清單裡。

## 第 ⑥ 片：素材

- [ ] 06-1 Supabase Storage 每組織一 bucket（**這一半活著，就是雲端版的素材落腳處**）；`creative_asset_root` 退役。原本的「素材檔上傳掛主題」隨 `app/ads/` 的主題概念一起死。

## 第 ⑦ 片：收尾

- [ ] 07-1 閘門收尾：前端 depcruise 擋 supabase-js 只在登入模組（**Playwright 那一半已於 2026-08-29 完成**，見 `frontend/e2e/smoke.spec.ts`）
- [ ] 07-2 部署前（選平台後）：Hey API TS client、Sentry、staging、CD（單一 job `supabase db push`）

## 小債（順手做，不排優先）

- [ ] **外殼切片留下的三筆，沒有閘門在守**，明細見 `docs/tech-debt.md` 第〇節。最急的是：`app/core/rule_cards.py` 8 張規則卡有 6 張失效（`budget_structure`／`sample_size`／`ad_creative_fatigue`／`pacing`／`health_lights`／`autonomy`），設定頁照樣顯示、照樣可以調，但調了不影響任何東西——**這是使用者看得到的謊**
- [ ] GitHub 四個安全開關（secret scanning／push protection／CodeQL／branch protection）需 GitHub Pro 或公開 repo——**等使用者決定**要不要付費；未付費前 CI 綠不擋合併，靠人工
- [ ] Dependabot #1（high）：前端間接依賴 `nanoid`（size=0 無限迴圈，開發工具鏈才用到）——動前端時 `npm audit fix` 順手收
- [ ] **上雲前必還（2026-08-28 使用者裁決：本機單人階段不修）** 邀請連結是「持有即可用」：`app/identity/routes.py` accept_invite 不比對 invite.email 與登入者 email；且 `AcceptInvitePage` 一掛載就自動接受，沒有確認步驟（03-3 審查 note 5）——等使用者裁決要不要改成 email 嚴格比對
- [ ] `pendingPath`（登入後導回原路徑）沒有時效也不會在登出時清掉：同一分頁先冷開邀請連結、之後做別的登入，會被靜默導回舊邀請頁（03-3 審查 note 4）
- [ ] 兩個繞過每月花費閘門的既有路徑（04-1a 審查 note）：`app/main.py:279` 設定頁「測試連線」（1 token 探測）、`app/intake/card_test.py:60-62` CLI 診斷工具（HTTP 碰不到）。風險小，但閘門既然蓋好了應該補齊
- [ ] `resolve_ai_credentials()` 的「DB 值打錯字→當 platform 處理」分支沒有測試覆蓋（04-1a 審查 note）
- [ ] 用自己金鑰（`own`）的組織看不到「調整月上限」欄位，切回 `platform` 時不好調——04-2 開放切換來源時一併處理（04-1a 審查 note）
- [ ] AI 成本對帳：`llm_task.cost` 是我們自己用 `app/llm/pricing.py` 算的**估算值**，不是 Anthropic 實際帳單。官方有 `/v1/organizations/cost_report`（按 workspace／api_key 分組，約 5 分鐘延遲，需 Admin API key）——上雲收費前要拿它跟自己的估算對一次帳，否則「每月上限」擋的是估算不是真錢（2026-08-28 查證）
- [ ] 404 信封兩種格式並存：`require_brand` 走 `NotFoundKind` 吐 `{"detail": …}`，`web.NotFound` 走 `handle_api_error` 吐 `{"error": {"code", "message"}}`（03-1 r1 審查 note 2）——第 ⑦ 片統一信封時一併收
- [ ] `app/tests/test_settings_api.py:142` 一條測試寫死 Windows 磁碟機路徑，非 Windows 跳過（`skipUnless`）；應改成跨平台斷言後拿掉 skip

## 里程碑之後（上雲後才動）

- [ ] U1 新手五鐵則落地：全站術語大掃除＋禁用詞機器閘門＋步驟指示常駐（契約鐵則 11–12 驗收）

2026-08-29：V1-02（每日預算對帳）、M1-01（Meta MCP 一鍵建）、M1-02（同意即執行）、
M1-03（放手檔執行器）、P1（成效回流接通）五張隨 `app/ads/` 一起死——它們全部建立在檔期、
成效快照、切角歸因這些已經不存在的概念上。要回頭看內容：`git show v0.2-ads-last:BOARD.md`。
