# Drill 7 — 重跑演練六的 B 側（MarketingOS，F38 之後），量 ROAS 有沒有追上 A（2026-09-29）

目的：同一套腳本、同一個評審規則、同一份品牌事實（`../drill-6/brand-facts.md`），只換系統版本（master `3ecc16fb`，F35–F38 已合併），
重跑 B 三期，對照 drill-6 的 A（4.27）與 B（0.88）。**演練中不修程式**；缺口只記錄（對回檔案行號），演練後再 `/dig`。

沿用：`../drill-6/contract.md`、`plan.md`（流程與期別）、`judge-rubric.md`、`persona-beast.md`、`../drill-4/persona-rules.md`。

## 只換了什麼

| 項 | drill 6 | drill 7 |
|---|---|---|
| A 側 | Opus 盲測三期 | **不重跑**，沿用 `.harness/scratch/drill6/rows_A_1..3.json`／`fit_A_*` |
| B 側系統 | `a7…`（F34 前） | master `3ecc16fb`（F35 文案一條路、F36 黃燈批、F37 單一成效管線、F38 證據／優惠預設關／限時帶截止日） |
| B 帳號 | beast.drill6@example.com | 新註冊 `beast.drill7@example.com`（新組織；不用 `brd_bughunt`） |
| B 建檔多兩件事 | — | 「品牌知識 → 事實」登記真的有的證據；座標頁優惠預設全關、真的有的才開（F38 的修復內容，照真實情境操作） |
| 同步 | 操作者手動 `request_sync` | 成效頁「重新讀取平台」（F37 ruling 2）；操作者只在 persona 按不到時代按 |
| 後端 | `scripts.drill.serve` | 同，`.claude/launch.json` `drill-backend`（8710）＋ `scripts.drill.worker` |

## 每期流程（B）

1. B 在系統裡建到「到平台完成」清單 → ⏸。
2. 操作者：`fake_meta mirror <brand>`（P2 起 `--append`）→ B 配對（讀回核對）→ `export_plan <brand> --period n --campaign <id>`。
3. 評審（Haiku、`judge-rubric.md`）出 `fit_B_n.json`。
4. `tw_sim run plan_B_n.json --judge fit_B_n.json --out rows_B_n.json --prior rows_B_<前期>…` → `fake_meta load-rows`。
5. 撥時鐘到期末 → `fake_meta pull <org> --since <期初> --until <期末>`（帳戶歷史）→ B 回系統「重新讀取平台」→ 判讀 → 結案 → 排下一期。
6. 第三期模擬完不回推。

期別與時鐘同 drill 6：P1 9/26–10/2、P2 10/3–10/9、P3 10/10–10/16；P1 規劃撥 9/26。
