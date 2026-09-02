---
id: 0003
decision: The frontend is React, rewritten whole; do not extend the Jinja server-rendered pages.
applies-to: [frontend/]
supersedes: none
status: in-force
---

# 前端整站改用 React 重寫，放棄升級既有 Jinja 架構

現況盤點（2026-08-05）確認：前端是純 Jinja2 伺服器端渲染，零 JavaScript、零圖表庫，CLAUDE.md 寫的 HTMX 實際上從未導入。重設計目標是圖表密集的駕駛艙（KPI 卡、趨勢圖、pacing 警示、常駐指南卡），曾評估的替代方案是「保留 Jinja＋補 ECharts＋HTMX 局部更新」——工程較小、風險較低，但使用者明確選擇 React 整站重寫，理由：這是決定產品最終走向的介面，不願意停在互動性打折的中間態。

落地方式選「一次到位」而非逐模組漸進切換（strangler）：後端 HTML 路由全數保留到切換日，開發期間舊介面照常可用，所以「一次到位」的實際風險只剩工期，不含可用性空窗；風險由「每模組完成即給使用者預覽驗收」控制。後端資料庫與核心邏輯不動，只新增 JSON 彙整 API。

## Consequences

- 過渡期同一份資料有兩套呈現（舊 Jinja＋新 React），切換日前的後端改動要兩邊都顧。
- 新增建置工具鏈（Node/Vite）要維護，這在純 Jinja 時代不存在。
- 145 條 HTML 路由在切換日後退役，屆時要清掉，否則變成殭屍碼。
- ~~決策 0038（純桌機 1440px）繼續有效，React 版不做響應式。~~ **已被 ADR 0051 取代（2026-09-02）**：外殼改為流動寬度，`max-width` 1920px，最窄可用到 1024px；平板與手機仍不做。
