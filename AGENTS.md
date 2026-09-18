# Brand Marketing OS — Codex 入口

在本專案開始工作時，讀取根目錄 `CLAUDE.md` 一次；已載入且未變更就沿用。依下一個決策需要選讀它指向的文件，Skill／Plugin 不另建平行規範。UI 原型使用 Harness demo；正式 UI 沿用 `docs/design-system.md`，設計技能只補本次尚未解決的問題。

Harness 技能由目前主機載入的位置解析。沒有收到 SessionStart 狀態且本次需要續接佇列時，依 `CLAUDE.md` 的開場步驟讀取相關現況；插件出現在技能清單不代表工具 hook 已啟用。
