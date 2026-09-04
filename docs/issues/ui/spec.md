# 目標：介面收尾（U1 文案閘門＋U3 配色字體＋排程頁結構）

Status: 待使用者點頭——換全站字體是產品外觀決定，不是順手改得的。
全文出處：`BOARD.md` @ commit `6574191`。依據：ADR 0051（介面是儀表板不是文件）。

- `issue-u3-font-and-palette.md` — ADR 0051 規則 13 明文另開的那一張。
- `issue-u1-banned-words-gate.md` — 規則 9–11 的機器閘門，跟 U3 同一張收。
- `issue-schedule-page-long-scroll.md` — 撞到〈不做一路下滑〉那條紅線，掛在 U3 底下。
- `issue-fluidcard-keep-or-delete.md` — 美術／產品判斷。

**已查證不是 bug，不要再開票**：「1833 寬的視窗、內容擠在約 700 寬、右邊一片空白」——700 寬的是
表單卡片（`--width-form: 42rem`），段落另有 `--width-prose: 68ch`，兩個都是刻意的可讀性上限，
方案卡片本身有用滿寬度。先看 CSS 再喊版面 bug。
