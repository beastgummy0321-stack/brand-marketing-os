---
id: 0001
decision: Trim methodology files in place; no progressive disclosure — the model has no tools to follow a pointer with.
applies-to: [app/methodology/, app/llm/methodology.py]
supersedes: none
status: in-force
---

# 方法論檔就地精簡，不採用 progressive disclosure

Anthropic 官方 Skill 撰寫最佳實務主打 progressive disclosure——主檔只留指路標，明細放旁邊檔案，模型需要時自己去讀，因為「reference files don't consume context tokens until actually read」。本專案**刻意不採用**：`app/llm/gateway.py` 是單次 Messages API 呼叫，沒有給模型任何工具，模型無法自己讀檔，指路標會指到一個它到不了的地方。

因此方法論檔一律**就地精簡**：每份檔案本身壓到最短，因為它每次生成都會被無條件整份注入。寫法準則是「規則＋理由」，而理由**只有在它是模型不知道的外部事實時才留**（平台演算法改版、台灣在地情境、實測數字）；模型自己推得出來的理由一律刪（官方：「Only add context Claude doesn't already have」；mattpocock 稱這類為 No-op）。來源標注與萃取履歷 frontmatter 全刪——只有人會看，卻每次生成都在付錢。

## Consequences

- 每次生成都付全額 token，模型端沒有「用不到就不載入」這條路。
  （2026-08-07 補註，見 ADR 0009：檔案**之間**已可依品牌開關挑選，但那是程式在呼叫 API 前
  依 DB 算好的，模型不參與；被選中的檔案仍是整份原文注入。本條講的是檔案**內部**不做指路標，
  這一點沒變。）
- 生成路徑哪天改成 agentic loop（模型能讀檔），這個決定就該重新檢視，改用官方的指路標架構。
- 精簡是不可逆的：原文已刪，砍掉的規則救不回來。
