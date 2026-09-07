# 目標：在本機跑完一輪廣告閉環，不上雲

Status: ①～⑦ 已走完（2026-09-04），⑧⑨ 的程式 2026-09-06 交件（票 01／02：判讀上畫面＋「採用」變規則卡）；
卡在資料不是程式——有座標的花費今天仍是 0 元。2026-09-06 演練抓到的五條已收，資料夾剩探針與待裁決的小票。

一輪 = 憲法第 4 條的那個環，走一遍：

```
①建品牌＋綁 Meta → ②排程頁填表出方案 → ③展開三層活動樹 → ④核准
→ ⑤產素材（帶七維座標）→ ⑥人照樹上的名稱在 Meta 手動建廣告
→ ⑦名稱精準比對綁定 → ⑧花費／ROAS 回流接上座標 → ⑨判斷 → 回到②
```

管線整條都在（`/plans`→`/tree`→`/tree/approve`→`/tree/bind`→`/creative`→`/creative-performance`→`/diagnosis`）。
依據：`CONSTITUTION.md`＋ADR 0050（資料模型之記錄）＋`docs/contracts/schedule.md`；三者不一致以 ADR 0050 為準。
舊閉環 `app/ads/` 已整個刪除，回頭看用 tag `v0.2-ads-last`。

## 現況（2026-09-07 直接查本機資料庫重驗，推翻上一版寫的 ①～⑦ 現況）

本機資料庫**沒有任何真實 Meta 資料**，最早一列是 2026-09-06——中間跑過 `supabase db reset`，
2026-09-04 那次真綁定連同它的方案與活動樹已經不在。查法與結果（`docker exec supabase_db_marketing psql`）：

- `llm_task` 最早 `started_at` 是 2026-09-06；`schedule_tree` 只有兩列，都是 09-06。
- `meta_ad_account` 只有一列，`connected_at` 2026-09-06 13:39，是 `app/tools/simulate_meta_spend.py` 建的。
- `channel_entity_map` 六列全部指向模擬器的假 Meta id（`1202516…`），`source_tree_task_id` 是模擬器那棵樹。
- `meta_entity_spend` 只有 2026-08-30～09-06 共 8 天、4 個廣告實體、合計 3,783 元，全部是模擬器灌的。
- `rule` 0 列——演練期間按過的「採用」沒有任何一列活下來。

所以 ⑧⑨ 的「有座標的花費是 0 元」這句仍然成立，但理由不是「綁上的廣告沒花錢」，而是
**這個資料庫裡從來沒有過真花費**。重驗方法不變：叫
`performance.brand_creative_performance(conn, "org_bughunt", "brd_bughunt")` 看七維 `values` 是否為空；
要判斷資料真假，看 `meta_ad_account.account_id` 是不是 `368741390835357`（真）還是 `000000000000001`（模擬器）。

- 每日拉取 worker 是獨立行程（ADR 0063，`啟動行銷系統.bat` 會順便開起來）；機器關著的日子沒人拉，手動補
  `uv run python -m app.meta.daily_pull`。
- 2026-09-07 順手修掉的兩個污染源（`app/tools/simulate_meta_spend.py`）：它原本用**真帳號 id**
  灌假花費（`meta_entity_spend` 的唯一鍵含 `ad_account_id`，共用就是把假錢混進真桶子，而且沒有反向清除），
  且無條件 `save_token()` 覆寫整個組織的 Meta 權杖。現在帳號 id 是 `000000000000001`，權杖只在沒有時才寫。
  真跑與模擬因此可以同時存在於同一個資料庫——**前提是模擬器指到另一個品牌**，不要指 `brd_bughunt`。

## 排序（離閉環多遠，2026-09-04 使用者裁決；會靜靜算錯錢的東西一律插回最前面）

1. `issue-variance-probe.md` — 探針要使用者自己跑一次，跑出數字才回頭重判。
2. 演練留下的待裁決小票（`issue-adopt-*.md`、`issue-bind-success-is-silent.md`、`issue-coordinate-guard-*.md`、
   `issue-creative-crashes-without-a-product.md`）——各自檔頭有「最小一刀」與要裁決的部分。
3. `issue-image-on-ad-node.md` — judged-no，檔案留著記結論，不要再問第三次。

## 你要做的（agent 做不了）——順序不能顛倒

「把剩下的節點貼進 Meta」這句話已經作廢：資料庫裡沒有一棵真樹了（見〈現況〉），沒有名字可以複製。
真跑要從 ② 重來一次，而且 ⑥ 的名字只能從**這一次新展開的樹**複製——Meta 那邊 09-04 建的舊名字對不上新樹。

1. `supabase db reset`——洗掉模擬器的假花費與六個 e2e 測試品牌。代價：現有 3 個產品要重建，種子帳號活著。
2. 重啟後端（`啟動行銷系統.bat`），用 `123@example.com` 登入。
3. **建檔精靈**把 `brd_bughunt` 的品牌事實與產品填起來（現在 `knowledge_version=1`＝空的）。不擋閉環，但方案品質差一階。
4. 綁 Meta：貼真權杖、選 BP AD（`368741390835357`）。
5. ②出方案 → 選一個 → ③展開 → ④核准 → ⑤產素材。**這一步吃 LLM 額度**（`BRAND_OS_LLM_PROVIDER=codex_cli`，
   2026-09-07 08:12 UTC 曾因 codex 額度用完連續失敗四次，錯誤訊息會直接寫在畫面上）。
6. 照「展開結果」的三層名字去 Meta 手動建、發布、**打開**。名稱一字不差，**分隔號是全形 `｜`，複製不要用打的**。
7. 回畫面按「配對」，三層都綁上才算數。至少兩個不同的座標值真的花到錢，⑧⑨ 才有東西可判。
8. 那則廣告的圖由你自己照提示詞生、手動上傳（`issue-image-on-ad-node.md`，判不做）。

## 里程碑

第一段 $0——整套在本機 `supabase start` 跑通，用真品牌走完一條路（2026-08-29、2026-09-04 各走通一次，只差 ⑧⑨ 的真數據）。
第二段才推免費層雲端（`docs/issues/deploy/`）。

## T6c 凍結的決定（2026-09-06 站①裁決；票 01／02 已依此交件——留著是因為下一張碰判讀的票要照它走）

交付形狀：**顯示 ＋ 每條建議一顆「採用」**，按下去把那條變成品牌規則卡（走「我不喜歡這方案」既有那條路）。
零新表、零 migration，使用者按過才算數。全自動回流被否決：AI 判錯的結論無人攔截地餵進下一輪，錯了看不出是哪裡錯。

```
畫面「跑一次診斷」→ 程式壓縮（純算術）→ 三次 LLM（素材／受眾／錢）
→ 程式收斂（去重＋按影響金額排序取前 5）→ 畫面顯示 → 每條「採用」→ rule 一列
→ 下次出方案的 prompt 自己吃到
```

| # | 決定 | 來源 |
|---|---|---|
| 1 | **打平線 = 1 ÷ 毛利率**，不是固定 1.0。毛利率三層：①本月官網訂單算出的實際毛利率 → ②規則卡 `gross_margin`（default 0.70，設定頁可改）→ ③都沒有就**不畫線**，畫面明說 | `ads-commerce.md:13`、`ab-testing.md:72`；三層順序＝使用者裁決 |
| 1b | 新規則卡走 `app/core/rule_cards.py` 的 `CARDS` 加一筆，不必 migration | `rule_cards.py:1-18` |
| 1c | 逐產品的打平線**這一版不做但不封死**：缺的是「這則廣告賣掉哪個 SKU」的歸因；欄位與 fallback 順序現在就留好 | `orders/repository.py:204-241`、`schedule/period.py:202-241` |
| 2 | 收斂靠程式不靠 agent：按影響金額排序**取前 5**（今天量到只有 4 個實體，日後長大不必再改） | ADR 0057 §6 |
| 3 | **三個固定 agent 按判斷維度分工**（素材／受眾／錢），不按廣告筆數扇出 | 2026-08-31 使用者定案（24-agent／130 條建議的失敗教訓） |
| 4 | 「樣本不足」不寫門檻常數；介面固定寫「方向性判讀，不是統計顯著的結論」 | `ab-testing.md:73`、`:75` |
| 5／11 | 餵給 agent 與畫面的 ROAS 一律**保守／樂觀兩個值＋覆蓋率**：保守＝營收÷全部花費、樂觀＝營收÷有追蹤到的花費。單一數字禁止 | `docs/contracts/schedule.md`「兩個 ROAS 都是真的」 |
| 6 | 方法論走既有對照表「成效判讀／下期草案」；接線不寫方法論 | `app/methodology/README.md:36` |
| 7 | `task_type` 用既有的 `performance_reading` | `app/llm/providers.py:151` |
| 8 | 零 migration：診斷結果存 `llm_task.rendered_output`；採用寫既有 `rule` 表，**`source_reference_id` 留 NULL**（塞 `llm_task.id` 違反 FK，plan review 實跑證明），來源寫進 `content` 文字 | `20260826000001_core_baseline.sql:49` |
| 9 | 採用寫出的規則 `severity` 一律 `soft`；`rule_type` 只用既有的 `angle`／`audience`／`budget_split` | `app/schedule/routes.py` `SOFT_REJECT_RULE_TYPES` |
| 10 | 觸發＝使用者按按鈕，不自動跑；「本月」窗口不另開——AI 看到的數字必須跟畫面那張圖是同一份 | 既有三個 `llm_task` 都是按鈕 |

探針逼出來的兩條規則（已落實）：**共線性由程式標出來**（一個維度底下每個座標值都只掛 1 則廣告、且多個維度分組完全相同時，
壓縮層要註明「這幾個維度分不開」）；**去重鍵 = (維度, 座標值, 方向)**，同鍵只留一條並記下幾個判斷器都這麼說。

## 消融砍掉的四件事（2026-09-04；不要再提案一次）

1. 「幫配對失敗訊息加一條 Playwright 斷言」——測試只收四類，「錯誤訊息措辭」不是。
2. 「開一支 `npm run e2e:real` 真跑驗收腳本」——它只驗得出「不是空的」，斷言比問題弱。留下來的是 T8b 那行 SQL。
3. 「版面另開一張票」——長頁那半掛回 `docs/issues/ui/`。
4. 「右邊一大片空白」——那是 `--width-form` 刻意的表單寬度上限。**先看 CSS 再喊版面 bug。**
