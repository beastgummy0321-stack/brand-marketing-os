---
id: 0002
decision: Cap the forced-load budget (CLAUDE.md and every .md it names), not the total .md line count on disk.
applies-to: [CLAUDE.md, docs/]
supersedes: none
status: in-force
---

# 文件膨脹只卡「強制載入預算」，不卡 .md 總量

2026-08-04 整個 `docs/` 因為膨脹到無法維護而被清空重來。事後檢討：拖垮專案的**不是文件存在**，而是 `AGENTS.md` 的權威順序表逼每個 session 都得讀它們。Anthropic 官方明講「No context penalty for large files：reference files don't consume context tokens until actually read」——沒被讀的檔案是零成本。

因此擋膨脹的閘門卡的是**強制載入預算**（`CLAUDE.md` ＋ `CONSTITUTION.md` ＋ 它們點名要讀的所有 `.md` 的行數總和，上限 500 行，對齊官方 SKILL.md 建議值。**根目錄的 `AGENTS.md` 於 2026-09-03 刪除**——它逐字寫著「SQLite、單機單人使用」，正是 `CONSTITUTION.md` 第 1 條禁止的前提，而它不在任何 sweep 的掃描樹裡；ADR 0031 也明文「workspace 不放 `AGENTS.md`」），**不是磁碟上 `.md` 的總行數**。沒被點名的參考資料想放幾份都可以。唯一的例外是 `app/methodology/`：那裡是程式無條件整檔注入，沒有「不讀」的選項，另外用 pytest 卡每檔 150 行（見 ADR 0001）。

## Considered Options

- **卡 `.md` 總行數**（最初的方案）——否決：會誤傷從來沒被讀過的參考資料，而且沒對準真正的成本來源。
- **純靠修剪紀律，不做自動檢查**（mattpocock/skills 的做法，整個 repo 零行數上限）——否決：本專案已經付過「純靠紀律會失效」的學費，前一版 `doc-diet.ps1` 因為要有人記得跑而變成孤兒。閘門做成 `PostToolUse` hook，寫檔當下自動擋。

## Consequences

- 想加一份必讀文件，就得先砍掉別的，或明確調高上限——變成一個要動手的決定。
- 修剪紀律靠 `CONTEXT.md` 的 Sprawl／Sediment／No-op／Duplication 詞彙，數字閘門擋不住「每行都還在但已經沒用」。
- `docs/adr/` 自己不進強制載入預算：它是查得到、但沒人被逼著讀的參考資料。
