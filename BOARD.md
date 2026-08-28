# 切片看板（只放未開始＋進行中；完成即刪行，歷史＝git log）

排序＝執行順序。分票唯一依據＝`docs/ui-migration-contract.md` v2（含隨批裁決）＋ ADR 0019。
標「需批准」的票動工前先提計畫等批准；動到畫面先過畫面契約（草圖 → 後端 → 前端）。



## 里程碑（2026-08-28 grill 定案）：第一段 $0——整套在本機 `supabase start` 跑通、用真品牌（建檔精靈重建）跑一期廣告閉環；第二段才推免費層雲端。看板順序＝執行順序。

## 第 ② 片：資料層一次翻（ADR 0027；saas 分支；票在 .scratch/saas/tickets/）——02-1～02-5、02-7 完成；收工前：`supabase db reset` 套 RLS 到 public＋全套一次

## 第 ③ 片：身分（需批准：schema＋權限）


## 第 ④ 片：設定與憑證（需批准：schema）

- [ ] 04-0b `app/ads/sync.py:457-459` `claim()`／`:486-487` `ignore()`：`SELECT * FROM discovered_campaign WHERE id = %s` 沒篩 org_id，唯一邊界是品牌層的 `claimed_brand_id != brand_id`——猜中 id 就能碰到別組織未認領的活動（04-0 §3 鄰居掃描發現）
- [ ] 04-1a（票 04-1a-ai-money-gate.md，已派 Sonnet）金鑰來源解析器（platform／own，不寫死）＋每組織每月 AI 花費上限硬擋，閘門放在 `app/llm/gateway.py:run_task()`（全站 27 個 AI 呼叫的唯一入口）
- [ ] 04-1b pydantic-settings 收環境變數＋組織時區（`org_timezone`，IANA，預設 Asia/Taipei，只改排程面的「今天」）＋`llm_task.methodology_hash`（動 schema，一個欄位）
- [ ] 04-2 憑證進 Supabase Vault（本機已裝 0.3.1）＋「已連接帳號」（組織）→ 綁定（品牌）＋順手補 K1（`tracking.py` INSERT 寫 `meta_ad_id`）
- [ ] 04-2 已連接帳號（組織）→ 綁定（品牌）；Meta／GA4 憑證進 Vault；順手補 K1（`tracking.py` INSERT 寫 `meta_ad_id`）

## 第 ⑤ 片：背景工作

- [ ] 05-1 procrastinate：`enqueue／status／cancel` 契約、worker 行程；`_auto_sync_loop`／週引擎／`_progress_state`／`_immediate_sync_cache` 全數搬入；R5-S「結束後 14 天自動收帳」成為第一個週期工作

## 第 ⑥ 片：素材

- [ ] 06-1 Supabase Storage 每組織一 bucket；素材檔上傳掛主題；`creative_asset_root` 退役

## 第 ⑦ 片：收尾

- [ ] 07-1 閘門收尾：前端 depcruise 擋 supabase-js 只在登入模組；1 條 Playwright（登入→建品牌→開檔期→駕駛艙）
- [ ] 07-2 部署前（選平台後）：Hey API TS client、Sentry、staging、CD（單一 job `supabase db push`）

## 小債（順手做，不排優先）
- [ ] GitHub 四個安全開關（secret scanning／push protection／CodeQL／branch protection）需 GitHub Pro 或公開 repo——**等使用者決定**要不要付費；未付費前 CI 綠不擋合併，靠人工
- [ ] Dependabot #1（high）：前端間接依賴 `nanoid`（size=0 無限迴圈，開發工具鏈才用到）——03-2 動前端時 `npm audit fix` 順手收
- [ ] **上雲前必還（2026-08-28 使用者裁決：本機單人階段不修）** 邀請連結是「持有即可用」：`app/identity/routes.py` accept_invite 不比對 invite.email 與登入者 email；且 `AcceptInvitePage` 一掛載就自動接受，沒有確認步驟（03-3 審查 note 5）——等使用者裁決要不要改成 email 嚴格比對
- [ ] `pendingPath`（登入後導回原路徑）沒有時效也不會在登出時清掉：同一分頁先冷開邀請連結、之後做別的登入，會被靜默導回舊邀請頁（03-3 審查 note 4）
- [ ] `CopyIconButton` 放在 `components/workbench/shared/`，已有 4 個跨功能呼叫端——照集裝箱憲章 §5 該升級成真正的共用位置（03-3 審查 note 6）
- [ ] 404 信封兩種格式並存：`require_brand` 走 `NotFoundKind` 吐 `{"detail": …}`，`web.NotFound` 走 `handle_api_error` 吐 `{"error": {"code", "message"}}`（03-1 r1 審查 note 2）——第 ⑦ 片統一信封時一併收
- [ ] `app/tests/test_settings_api.py` 一條測試寫死 Windows 磁碟機路徑，02-7 在非 Windows 跳過（`skipif`）；應改成跨平台斷言後拿掉 skip

## 里程碑之後（Meta 端解封或上雲後才動；2026-08-28 grill 定案）

- [ ] V1-02 脈動有沒有照做，機器要抓得到：現在自動對帳只比總花費不比每日預算（`reconcile.py` 檔頭：各幣別單位換算不一，比錯就狼來了），使用者不照排程調日預算抓不出來，只有對帳三題自答（`guardrails.py:157`）答「不一樣」才會降可信度。要機器自動抓，得讓 `build_actuals` 撈回 Meta 的每日預算——**被 M1-01 擋**。
- [ ] M1-01 Meta MCP 整期一鍵建（**暫緩，2026-08-23**）：連線與參數都已驗證可用，但 Meta 以錯誤 31／子碼 3858385 擋住「用 API 建立或修改廣告」——已知的 Meta 端問題（開發者社群 thread 845129991936233），後台看不到待辦事項、無入口可完成驗證，後台手動操作不受影響。系統使用者 token 未被 Ads MCP 文件列為支援，未驗證。改走 ADR 0023 保留的手填 ID 路徑；Meta 端解除後本票即可續跑。
- [ ] M1-02 收件匣同意即執行（停用／降額；加碼再一道金額確認）＋安全底線（需批准；被 M1-01 擋）
- [ ] M1-03 放手檔執行器（需批准；被 M1-02 擋）
- [ ] P1 成效回流接通：帶單切角下期加權＋反回音室自動避開（兌現 nextcycle 既有承諾；**必須在 M1 之後**——切角歸因依賴 M1 回寫的 external_ad_mapping，ADR 0022 第 6 條）
- [ ] U1 新手五鐵則落地：全站術語大掃除＋禁用詞機器閘門＋步驟指示常駐（契約鐵則 11–12 驗收）；含鐵則 9 清理——weekly 通知雙出口（dashboard/repository.py:207，票 06 起既有）
