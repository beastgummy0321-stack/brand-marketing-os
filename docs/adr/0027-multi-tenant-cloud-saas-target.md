# 0027 目標＝多租戶雲端 SaaS；單機單人不再是設計前提（2026-08-26 定案）

使用者發起，第三方視角盤點（8 條 Haiku 掃描＋12 條 Sonnet 覆核）後 grill 五輪 35 題逐條定案。
背景事實：系統未發布、資料全為測試；商業邏輯（判讀、下期建議、學習帳、方法論注入、LLM 閘道）
可原樣保留；把系統釘在單機的是 5 個地基：全域單一 DB 連線＋大鎖（`app/shared/web.py:46`、
`app/core/db.py:97-123`）、無登入無使用者概念（`require_actor()` 固定回 `OPERATOR`）、
設定與金鑰全站一份且明文（`app_setting` 無 brand_id）、背景工作靠行程內執行緒與全域變數
（`app/main.py:121-122,147-148,252`）、檔案在本機硬碟。

## 決定

1. **部署形態：雲端唯一。** 桌面版退場；本機只是開發環境（`supabase start`）。
   SQLite 徹底退場，測試也跑 Postgres。
2. **租戶模型三層：組織 → 使用者 → 品牌。** 每個使用者註冊時自動建一個**個人組織**（畫面永不顯示）；
   點「我是公司／組織」＝替組織取名並開放邀請。品牌屬組織，成員離開資料留下。
   組織內只分**擁有者／成員**；更細的品牌層權限是加法，不先設計。
3. **平台：Supabase**（Postgres＋Auth＋Storage＋Vault；pgvector 備用），專案地區東京。
   - 身分：Supabase Auth；後端以 JWKS 非對稱金鑰驗 JWT，每個請求帶身分。
   - 前端 `@supabase/supabase-js` **只做登入**；資料一律走 FastAPI `/api/*`。
     前端 depcruise 擋 `supabase-js` 只准出現在登入模組。
   - Migration 交 Supabase CLI：集中 `supabase/migrations/`，檔名帶模組前綴；
     機器閘門「migration 只能 CREATE 自己模組前綴的表」守模組邊界。自家 runner 與
     `migration_manifest.json` 退役。
   - **重做基線**：每模組一份新的 Postgres 方言 `0001`，`org_id NOT NULL` 一開始就在；
     舊 SQLite migrations 整批刪，不寫任何過渡 migration。
4. **資料層：原生 SQL 保留，不引進 ORM**；`psycopg[pool]` 每請求一條連線，全域 `conn` 與大鎖拆除。
   租戶隔離在後端一律以 `org_id` 過濾，升級 `test_brand_isolation_all_tables.py` 為
   「每張表必有 org_id」機器閘門。
5. **背景工作：`procrastinate`**（Postgres 原生、SKIP LOCKED、重試、週期排程），獨立 worker 行程。
   handler 契約：可重跑、只碰自己組織的資料、失敗丟例外由 worker 記錄；ADR 0024 第 5 條
   「每個 Action 各自 try/except、三次失敗升級出卡」精神不變。每日備份模組退役（平台自帶）。
6. **憑證與設定**
   - AI 金鑰平台付（伺服器環境變數），用量按組織記錄（沿用 `llm/pricing.py`）。
     模型選擇改為**組織層**設定；多模型／客戶自帶金鑰只留 Provider 協定接縫，等第一個企業戶。
   - Meta／GA4：**組織層「已連接帳號」清單 → 品牌「綁定」其中一個**，憑證存 Supabase Vault。
     第一版仍貼 token／上傳 JSON，之後換 OAuth。
7. **素材檔上傳進系統**（Storage，每組織一 bucket），掛在主題下；成效判讀仍只到主題（ADR 0008 不變）。
8. **手動路徑永遠一級公民**：自動化不得讓手動路徑退化。自動度存品牌層（ADR 0018 第 4 條），
   「下次不再提醒」存使用者層。M1–M3 降為 Meta 解封後的加法。
9. **不做**：付費／方案、i18n、Convex、RLS（前端不直連 DB 故不需要）、起手範本（借 JWT middleware 寫法即可）。
10. `app/mock_data.py` 改名 `app/core/vocab.py`（它是詞彙常數表）；`DEMO_BRANDS`、`seed_demo.py` 刪除。

## 取代／修正的既有決策

| 既有 | 處置 |
|---|---|
| ADR 0004 取消具名授權 | **取代**。`require_actor()` 回真實使用者；`authorized_by` 記使用者 id |
| ADR 0018 不可逆項目「沿用背景執行緒＋輪詢」 | **修正**為 procrastinate；其餘條款不變 |
| ADR 0020 背景工作連線注入 | 不變（注入的變成連線池借出的連線） |
| ADR 0024 第 4 條「掛既有執行緒」 | **修正**為 procrastinate 週期工作；第 1–3、5–6 條不變 |
| CONTEXT.md「單張素材檔案不進系統」「素材資料夾」 | **取代**為「素材檔」 |
| CLAUDE.md「單機單人使用」 | **刪除**，改為本 ADR 的目標宣告 |
| `app/*/migrations/` 各模組一資料夾＋hash 凍結 | **取代**為 Supabase CLI 集中資料夾 |

## 順序

① 憲法＋詞彙＋資料狀態聲明 → ② 資料層一次翻（唯一斷線期，開在 `saas` 分支）→ ③ 身分 →
④ 設定與憑證 → ⑤ 背景工作 → ⑥ 素材上傳 → ⑦ 機器閘門收尾。看板既有票全部排在其後。
留底：主線打 tag `v0.1-desktop` 推上遠端；同一 repo 開 `saas` 分支，不開新 repo。

## 理由

- 語言與框架（Python／FastAPI／React／SQL）本來就是 SaaS 常用組合；錯的不是選型，是指令檔把目標寫成單機，
  每個 agent 照憲法替使用者「省」。改憲法比改程式先。
- 無外部使用者、每週 70 小時、資料可丟——資料層一次翻比雙軌並行便宜且不留過渡碼。
- 現成零件全部查證過版本、授權、更新日期（2026-08-26）：psycopg 3.3、procrastinate 3.9、supabase-py 2.31、
  PyJWT 2.13；不自建連線池、工作佇列、migration runner。

## 當時排除了什麼

- 桌面版與雲端並存：讓「單機」藉口回流，資料層雙軌。
- 使用者→品牌兩層：之後加團隊要重做權限並搬資料。
- 自建登入：把重設／鎖定／外洩責任攬在自己身上。
- ORM：60 個檔的 SQL 已寫好，ORM 是重寫加一層翻譯。
- Celery＋Redis：每分鐘上千工作前用不到；procrastinate 的 handler 契約留好即可換。
- 自寫 job 表＋worker 迴圈：procrastinate 就是那張表加 worker，還多重試與定時。
- 前端直連 Supabase 靠 RLS：養出第二條邏輯路徑。
- 新 repo：ADR、看板、閘門、歷史都是 agent 的記憶。
