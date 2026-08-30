# 切片看板（只放未開始＋進行中；完成即刪行，歷史＝git log）

排序＝執行順序。標「需批准」的票動工前先提計畫等批准；動到畫面先過畫面契約（草圖 → 後端 → 前端）。

## 里程碑（2026-08-29 排程模組併回 `saas` 後改寫）

第一段 $0——整套在本機 `supabase start` 跑通，用真品牌走完一條路：
**排程頁填表 → 出 N 個方案 → 選一個展開成三層活動樹 → 人照樹上的名稱在 Meta 後台自己建、
自己投放 → 名稱配對把成效綁回方案**。第二段才推免費層雲端。

2026-08-29 併回 `saas` 當天，用晨光咖啡＋BP AD 真帳號整條走完（LLM 走本機 codex CLI＝$0；
Meta 端只建了一個 **PAUSED、沒有廣告組合、沒有廣告、沒有預算**的活動殼，沒有任何投遞、
沒有任何花費）：表單 → 三個方案（含即時查證的來源）→ 金額分配 → 三層活動樹 →
手動在 Ads Manager 建好 → **名稱配對成功、存下平台 id（120251565102190671）→ 平台端改名，
連結不斷**。每日花費拉取拿的是 BP AD 真實數字。缺的**素材**補了一半：文案已於 2026-08-30 落地
（`92e95af`，樹上每個廣告節點都拿得到可貼的文案）；圖片本身還沒有，落腳處是第 ⑥ 片 06-1。

原本寫的是「用真品牌跑一期廣告閉環」。**那個閉環就是 `app/ads/`**，已於 2026-08-29 整個
刪除（21,595 行；要回頭看用 tag `v0.2-ads-last`）。回收成效（CSV 匯入）、覆盤、下一期都
**不在 v1**（`HANDOFF-shell-slice.md` §3.1，該檔已於本次併入後刪除，內容進 git log 與本看板）。

## 第 ⑤ 片：背景工作

- [ ] 05-1 procrastinate 的 `enqueue／status／cancel` 契約、job 註冊表。**安裝與 worker 進場點已完成**（票 01＋ADR 0038／0039：自己的 schema、worker 是 uvicorn 行程裡的一個 asyncio task，由 FastAPI `lifespan` 開關）。目前實際跑在上面的只有 Meta 每日花費拉取；`_progress_state`（brand_web 的 library／products 各一份）仍在待搬清單裡

## 第 ⑥ 片：素材

- [ ] 06-1 Supabase Storage 每組織一 bucket（雲端版的素材落腳處）；`creative_asset_root` 退役

## 第 ⑦ 片：收尾

- [ ] 07-1 閘門收尾：前端 depcruise 擋 supabase-js 只在登入模組（**Playwright 那一半已於 2026-08-29 完成**，見 `frontend/e2e/smoke.spec.ts`，`cd frontend && npm run e2e` 一行跑完）
- [ ] 07-2 部署前（選平台後）：Hey API TS client、Sentry、staging、CD（單一 job `supabase db push`）
      ＋**pydantic-settings 收環境變數**（2026-08-30 從第 ④ 片移來）：現在 19 個地方各自讀
      環境變數、8 個不同的鍵，缺了或打錯字會安靜地用預設值繼續跑。它真正值錢的時刻就是
      第一次部署——開機當場大聲失敗，好過上線後某個功能莫名不動、查半天發現少一個變數
      ＋**部署映像檔要有 IANA 時區資料庫**（04-1b 的 `today_for_org()` 靠 `zoneinfo`；本機是
      psycopg 順帶裝的 `tzdata`（只在 Windows），Debian 系映像檔內建，Alpine 沒有——沒有就
      開機第一次算日期時大聲炸掉，這是刻意的，不要讓它安靜退回 UTC）
- [ ] 07-3 統一 404 信封（2026-08-30 從小債移來）：`require_brand` 走 `NotFoundKind` 吐
      `{"detail": …}`，identity 路由走 `handle_api_error` 吐 `{"error": {"code","message"}}`；
      前端三處讀 `.detail`（`brandReportApi.ts:36`、`http.ts:116`、`ordersApi.ts:93`）要跟著改。
      這是 API 契約改動，不是順手小事（03-1 r1 審查 note 2）
- [ ] 07-4 GitHub 四個安全開關（secret scanning／push protection／CodeQL／branch protection）：
      需 GitHub Pro 或公開 repo。**2026-08-30 使用者裁決：本機單人階段先不付費**，
      跟 Sentry／staging／CD 同一批再決定；在那之前 CI 綠不擋合併，靠人工

## 小債（順手做，不排優先）

2026-08-30 清掉一輪（死連結、行銷目標記憶、六張失效規則卡、pendingPath 時效、
測試連線繞過花費閘門、兩條測試缺口）；「兩個後端吃光連線槽」是知識不是債，進了
`CLAUDE.md` 的 Tests 段。剩下這些各有理由。

Dependabot #1（`nanoid`，修補版是 3.3.18）：**`saas` 這邊已經是 3.3.18、`npm audit` 零漏洞**，
但 GitHub 掃的是預設分支 `master`，那邊還是凍在 `v0.1-desktop` 的 3.3.17。所以警示會一直亮到
`saas` 併回 `master` 為止——**不是還沒修，是修在另一條線上**。不為了關掉警示單獨去動凍結的 master。

- [ ] **上雲前必還（ADR 0039）** 每日 Meta 花費拉取的 worker 跑在網站行程裡：網站沒開就不拉，
      那天沒有數字（handler 可重跑，但沒人叫它就沒人補；手動補：`uv run python -m app.meta.daily_pull`）；
      cron `0 3 * * *` 觸發的**時刻**仍是機器本地時間（04-1b 已經讓「拉到的數字算在哪一天」
      改用組織時區，所以早拉晚拉不再標錯日期；剩下的是觸發時刻本身）。上雲時 worker 要拆成自己的行程
- [ ] **上雲前必還（2026-08-28 使用者裁決：本機單人階段不修）** 邀請連結是「持有即可用」：
      `app/identity/routes.py` accept_invite 不比對 invite.email 與登入者 email；且 `AcceptInvitePage`
      一掛載就自動接受，沒有確認步驟（03-3 審查 note 5）
- [ ] 用自己金鑰（`own`）的組織看不到「調整月上限」欄位，切回 `platform` 時不好調——
      跟「設定頁切換金鑰來源」同一張做（2026-08-30 隨那張一起移到「里程碑之後」，04-1a 審查 note）
- [ ] AI 成本對帳：`llm_task.cost` 是我們自己用 `app/llm/pricing.py` 算的**估算值**，不是 Anthropic
      實際帳單。官方有 `/v1/organizations/cost_report`（按 workspace／api_key 分組，約 5 分鐘延遲，
      需 Admin API key）——上雲收費前要拿它跟自己的估算對一次帳，否則「每月上限」擋的是估算不是真錢（2026-08-28 查證）
- [ ] **需裁決**：設定頁「整組複製提示詞的自訂開頭」整塊已死（2026-08-30 清規則卡時順手發現）——
      `image_prompt_batch_header` 除了自己存、自己讀回來顯示，沒有任何程式在用；它服務的「整組複製」
      按鈕在素材工作檯裡，那個畫面已隨 `app/ads/` 刪掉。跟六張失效規則卡同一種謊。刪它要連
      `AssetsSection.tsx` 那一區＋`POST /api/settings/prompt-header`＋兩條測試一起走

## 刪 `app/ads/` 那天一起死（2026-08-30 掃描 → 四張票已全部落地，剩下這些）

掃法：四個角度平行掃全 repo，每筆再派人專門去證明它是錯的，證不倒才留。32 筆去重後做完了
11 項（票 02–05，commit `d9b2c90`／`454f8a8`／`7e0697e`／`2571b73`）。剩下這些各有理由。

- [ ] **需批准（schema）** 兩支 migration 被這輪刻意留著沒寫：
      `DROP TABLE decision`（沒讀也沒寫，它的主人 `app/core/orchestrator.py` 已刪）＋
      刪 `order_record.attribution_override`、`interrupt.kind`／`visible_from`／`campaign_cycle_id`
      四個沒人用的欄位。欄位還在，所以 `enqueue()` 那三個沒有生產呼叫端的參數也還留著
- [ ] `frontend/src/components/layout/FluidCard.tsx` 現在只剩 Storybook 在用（票 05 拆掉
      `TaskFlowShell` 的三個死參數之後）。要留當設計素材還是刪，下一輪順手決定
- [ ] `frontend/src/lib/auth.ts` 的 depcruise 註解已改成「規則還沒建」並指向 07-1——
      真正把規則建起來還是 07-1 的工作

## 使用者待辦（不是程式債，做的人是你；我做不了，所以不放小債）

- [ ] 晨光咖啡 0 筆已確認事實、0 條規則：產品名稱已經會進 prompt（2026-08-29 修），但品牌上下文
      仍是空的——代理不知道這個品牌是誰、賣多少錢、對誰賣。去建檔精靈把事實填起來，方案才會再準一階
- [ ] 變異度（同一份輸入跑 N 次結果差多少）從沒量過：探針在
      `D:\0UserProfile\Desktop\MarketingOS Shell\variance-probe\`，一次都沒跑過。排程會做即時網路查詢，
      兩次跑本來就看到不同素材，重試預算現在是猜的。
      **這條也是「提示詞指紋」的前置**：`llm_task.methodology_hash`（原 04-1b 的一部分，一個
      欄位，動 schema）是用來回答「為什麼這個月的方案跟上個月不一樣」，但差異本來有多大都
      還沒量過，先蓋工具去解釋差異＝替一個沒人跑過的系統猜門檻。**2026-08-30 判定不做**；
      這條探針跑出數字之後才回頭重判

## 里程碑之後（上雲後才動）

- [ ] U1 新手五鐵則落地：全站術語大掃除＋禁用詞機器閘門＋步驟指示常駐（契約鐵則 11–12 驗收）
- [ ] 設定頁切換金鑰來源（`platform`／`own`，2026-08-30 從第 ④ 片移來）：前提是「自帶金鑰」
      真的是一個在賣的方案，那還不存在——今天要切只能直接改資料庫，而全系統只有一個組織。
      做這張時一併補上面小債那條「用自己金鑰的組織看不到調整月上限欄位」

2026-08-29：V1-02（每日預算對帳）、M1-01（Meta MCP 一鍵建）、M1-02（同意即執行）、
M1-03（放手檔執行器）、P1（成效回流接通）五張隨 `app/ads/` 一起死——它們全部建立在檔期、
成效快照、切角歸因這些已經不存在的概念上。要回頭看內容：`git show v0.2-ads-last:BOARD.md`。
