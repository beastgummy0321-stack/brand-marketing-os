# Drill 6 — 外部廣告商 vs MarketingOS，三期、兩次回推（2026-09-26）

使用者裁決（2026-09-26）：7 天 ×3 期；兩邊日預算 NT$1,500；B 用 Sonnet 5；A 盲測不看系統。
目的：找出系統相對「專業投手」欠缺什麼，產出綠／黃／紅待辦。**演練中不修程式**（README）。

## 角色

| 角色 | 模型 | 產出 | 禁區 |
|---|---|---|---|
| A 外部廣告商 | Opus | `.harness/scratch/drill6/A/research.md`、`plan_A_<n>.json`（contract.md 格式）、每期 `review_A_<n>.md` | 不讀 `app/`、`frontend/`、`docs/`（drill-6 三份除外）、不開 localhost |
| B 阿虎（`persona-beast.md`） | Sonnet | `.harness/scratch/drill6/B/run_<n>.md`＋截圖 | drill-4 persona-rules |
| C 評審（LLM） | Haiku | `fit_<side>_<n>.json`（judge-rubric.md） | 不看另一邊、不看數字 |
| C 模擬器 | 程式 | `rows_<side>_<n>.json`＋報表 | — |
| 操作者 | 本 session | 環境、鏡射、載入、匯出、回推、根因、三色清單 | 演練中不修 |

## 環境（操作者）

```
.venv/Scripts/python.exe -m scripts.drill.fake_meta reset
.venv/Scripts/python.exe -m scripts.drill.serve --port 8710      # 後端＋替身＋演練時鐘
.venv/Scripts/python.exe -m scripts.drill.worker                 # worker＋替身＋演練時鐘
.venv/Scripts/python.exe -m scripts.drill.clock set 2026-10-02   # 每期結束時撥時鐘再 pull
```

B 自己註冊新帳號、新品牌（不用 `brd_bughunt`：那裡有真 Meta 綁定與六個舊活動，會混進判讀）。
替身權杖 `EAAG-drill-token-beast` → 帳戶 900000000000006。

## 每期流程

1. A 寫 `plan_A_n.json`；B 在系統裡建到「手動發布清單」→ ⏸ 交接。
2. 操作者：`fake_meta mirror <brand>`（第二期起 `--append`）→ B 配對 → `export_plan <brand> --period n`。
3. 評審：兩份 plan 各出 `fit_*.json`。
4. 模擬：`tw_sim run plan --judge fit --out rows --prior <前幾期 rows>`；B 側 `fake_meta load-rows <brand> rows_B_n.json`。
5. 撥時鐘到期末 → `fake_meta pull <org> --since <期初>` → B 回系統看成效／判讀／結案／排下一期；A 收 `tw_sim report` 表格寫 `review_A_n.md` 再排下一期。
6. 第三期模擬完不回推，當最終成績。

期別：P1 9/26–10/2、P2 10/3–10/9、P3 10/10–10/16。時鐘：P1 規劃＝真實 9/26；P1 結算撥 10/02；P2 規劃撥 10/03、結算 10/09；P3 規劃撥 10/10、結算 10/16。

## 彙總（五個維度＋三色）

商品洞察深度、受眾與時機、素材與出價結構、學習閉環（下一期真的照結果改了嗎）、操作摩擦（B 的分數）。
綠＝系統做得到且不輸 A；黃＝做得到但較差或需人工；紅＝功能缺、bug、停止條件、排出不能投的東西。
每條缺口先對回程式碼證實（唯讀 agent），再上清單。模擬數字只比相對，不證明真投放會賺。
