# Drill 4 — 上線前最終內測：三個陌生人各走兩圈 Golden Path（已核准）

日期：2026-09-13 規劃。使用者 2026-09-13 核准四項：先修「投放中可結案」再開始（修完等使用者說開始）、
`supabase db reset`、LLM 維持本機 codex、三人依序。執行中不修程式（README 規則）。

## 要回答的問題

Golden Path：**Goal → Decision → Production → Execution → Outcome → Learning → Next Decision**。
三個從沒看過產品的人，各自建品牌、跑兩個 Campaign，第二個 Campaign 的策略要真的吃到
第一個的學習。每一站都要有證據（畫面截圖＋操作者查資料庫），不是人說「好像有」。

同時回答：新手能不能只按「下一步」走完；老手能不能在同一頁微調；系統有沒有說謊
（印 0、印一段不存在的原因、假的自動化）。

## 角色與模型（依任務複雜度派發）

| 角色 | 檔案 | 模型 | 為什麼 |
|---|---|---|---|
| 小杰（沒耐性、亂點、不讀說明） | `personas/jay.md` | Haiku | 行為簡單：看到按鈕就按、超過十秒就重整。便宜、快。 |
| 阿明（第一次自己下廣告、怕按錯） | `personas/aming.md` | Sonnet | 要讀懂畫面文字、判斷「我現在該幹嘛」，需要中等理解力。 |
| Vivian（三年投手、質疑 AI） | `personas/vivian.md` | Opus | 要評價策略依據、預算算術、術語精確度，最難的判斷。 |
| 操作者：環境、替身、資料庫查證、log 整理 | — | Haiku（harness:utility） | 純事實工作。 |
| 操作者：成因、評分彙整、backlog 撰寫 | — | Opus（harness:planner） | 需要跨角色比對與架構判斷。 |
| 主持：與使用者討論、放行、最終報告 | — | Fable（本 session） | 留在這裡。 |

角色守則沿用 README：**不讀原始碼、不查資料庫、不讀 docs、不問人**；只回報畫面上看到的
症狀與證據。文字輸入一律 Playwright `fill`（中文已驗證不會亂碼）；每張截圖存進
`.harness/scratch/drill4/<persona>/`，用 `file` 確認是 PNG 才算證據。

## 環境

- `supabase db reset` 清成種子狀態（測試資料可丟；Beast Gummy 的 F04 走查資料一併清掉）。
- 後端以 **Meta 替身** 起：`python -m scripts.drill.fake_meta reset` →
  `python -m scripts.drill.serve --port 8710` → `python -m app.worker`。
  三個角色各自註冊自己的組織與品牌，各拿自己的替身權杖（`EAAG-drill-token-<persona>`），
  互不可見（第一次演練的教訓）。
- LLM 走 `.env` 的 `BRAND_OS_LLM_PROVIDER=codex_cli`（本機、免費）。**AI 產出品質的評價
  因此是在評本機模型**；管線是否接通與畫面是否誠實不受影響。
- 角色**依序**跑（阿明 → 小杰 → Vivian），每人約 1.5～2 小時；替身的 mirror／spend／pull
  由操作者在每人「配對」之後執行。三人平行可省時但替身狀態檔共用、codex 併發未知，不建議。

## 每個角色走的兩圈（同一張派工單，兩圈只差第二圈要看得到第一圈的學習）

| 站 | 角色做什麼 | 操作者查什麼（證據） |
|---|---|---|
| Goal | 註冊 → 建檔精靈（貼品牌事實、兩個商品含售價成本）→ 投放中心 → 用一句話描述目標（含金額、CPA 或 ROAS、月份）→ 理解如下 → 改一格 | `ads_campaign.goal_text／success_*／context_json.field_sources`；改過的格是 `user` |
| Decision | 策略頁：讀「主要原因」「最大的未知」「這輪想學到什麼」、展開「調整建議」「查看完整判斷」→ 按「照這個方式進行」 | `llm_task`（兩次呼叫，不多）、`ads_delivery_group／ads_ad` 列數與日預算合計×天數＝畫面總額 |
| Production | 素材分頁 → 派工到素材工作檯 → 在工作檯生成文案與圖片提示詞、選定、核准整包 → 回投放中心看「已就位（工作檯）」 | `workbench_pack.approved_at`；`asset_readiness` |
| Execution | 發布 Campaign → 看到「自動發布未接上」→ ⋯ → 手動發布清單（複製）→ 操作者 `fake_meta mirror <brand>` → 角色按「配對」→ 投放中 | 三層 `external_id` 皆綁、`ads_action` 有 publish／bind 列 |
| Outcome | 操作者 `fake_meta spend --round 1` → `pull <org>` → 角色在成效分頁按「重新整理成效」，讀數字與說明 | `ads_outcome_daily` 只有 group／ad 列；畫面沒有 0 冒充未追蹤；ROAS 保守主數字 |
| Learning | 角色結案（需先修「投放中可結案」）→ 讀判定與學習句 | `learning_ledger` 一列（confidence 已觀察）；CPA／購買目標因 F05 才讀購買數會判「看不出」＝預期；ROAS 目標可判達成／未達成 |
| Next Decision | 第二個 Campaign（同商品、下一個月）→ 策略頁「查看完整判斷」列出第一圈的學習；比對兩圈的配置與理由是否朝學習的方向動 | `budget_basis_json.basis.learnings` 含上一筆 id；操作者記錄兩圈 allocation 差異 |

## 評分與停止條件

沿用 README：每一步 1～10 分，7 分以下要截圖＋畫面上那句話；四個停止條件（算錯錢、跨租戶
可見、資料毀損、畫面死路）任何一個立即停。

## 通過標準（上線前內測）

1. 三個角色都走完兩圈，沒有觸發停止條件。
2. 七站每站都有操作者查到的資料庫證據；Next Decision 那站：第二圈的策略依據列出第一圈學習，
   且配置／理由與學習方向一致（不一致要能說出為什麼）。
3. 阿明（新手）在主路徑上沒有任何一步 ≤4 分；小杰的亂點沒有造成資料錯亂；Vivian 提出的
   「憑什麼」都能在「查看完整判斷」找到答案。
4. 零 HTTP 5xx；錢的不變量成立（各組日預算 × 天數 ＝ 畫面總額；成效總額只加 group 列）。
5. 畫面沒有任何 0／空白冒充「未追蹤／尚未設定」；沒有因果句（「主要原因是…」）出現在成效。
6. 所有 <7 分的步驟都變成 `docs/backlog/` 一檔一條（含成因，由操作者查證後才寫）。

## 已知、不算缺陷（角色回報時對照）

- 自動發布未接上（設計如此）；平台設定進階欄位是灰色佔位。
- Meta 路徑購買數未追蹤 → CPA／購買目標的結案判定「看不出」（F05 讀購買數）。
- 沒有「建議／採用／為什麼」、沒有第二批素材派工、沒有品牌智庫學習分頁（F05）。
- 策略「主要原因」夾英文欄位名（F05 提示詞用字）。

## 內測前必修（一張小票，執行前完成）

- **投放中可結案**：狀態 `live` 的成效分頁要有「立即結案」（附說明「提前結案會用目前的成效判定」），
  否則角色到不了 Learning；後端 `closeout.close` 本來就允許。

## 產出

- `.harness/scratch/drill4/<persona>/run.md` ＋截圖（拋棄式）。
- `docs/drills/README.md` 加「第四次演練結果」一節；每個缺陷一檔 `docs/backlog/`。
- 最終內測報告（本 session 給使用者）：七站 × 三人的通過表、缺陷排行、上線與否的建議。
