# 目標：裝一次就永久自動執行的閘門

Status: 待做——三份 issue，其中檔案層 import 環掃描使用者 2026-09-04 已批准，只差開票。
全文出處：`BOARD.md` @ commit `6574191`。

規矩（不是票，掛在未來每一張票上）：
- 契約頁隨票補：16 個模組現有 6 份，`ContractPageRatchetTest`＋`MODULES_WITHOUT_CONTRACT`
  （`test_architecture_boundaries.py:1706`）只准變短。動到某模組的 route C 票先補那個模組的頁。
- `app/identity/` 沒有任何 ADR 管——下一個碰 identity 的 route C 問題順手寫第一份。
- 新閘門一定要證紅，而且不只證一種紅法（2026-09-04 兩個閘門靠運氣過：`scrollWidth` 公式、七維 regex）。
