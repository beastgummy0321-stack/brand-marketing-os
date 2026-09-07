# 目標：介面收尾（U1 文案閘門＋演練待裁決）

Status: 設計系統已定（2026-09-07，`docs/design-system.md`，ADR 0065）；U3 配色字體結案。
依據：`docs/design-system.md` 是唯一前端規則；票裡不得另寫外觀規則，只引它的章節。

- `issue-u1-banned-words-gate.md` — 設計系統 §8 的機器閘門，仍是 backlog。
- `issue-schedule-page-long-scroll.md` — §1 第 1 條；GPT 2026-09-07 重整已拆成 ScheduleSetup／PeriodPanel／PlanComparison，待真瀏覽器驗收後刪。
- 其餘 `issue-*.md` — 2026-09-06 演練的待裁決票。

**已查證不是 bug，不要再開票**：「1833 寬的視窗、內容擠在約 700 寬、右邊一片空白」——寬度上限
（`--width-form`、`--width-prose`）是刻意的可讀性上限，見設計系統 §5 末段。先看 CSS 再喊版面 bug。
