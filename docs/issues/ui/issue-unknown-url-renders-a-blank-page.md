# 打不到的網址 → 整頁純白：沒有錯誤、沒有導覽、沒有回去的路

Status: open（drill 2026-09-09，小杰 step 9）。本輪唯一長成停機條件 4
（「畫面死掉且沒有下一步」，`docs/drills/README.md`）的東西。**這次是驅動打錯網址才撞到，
沒有任何點擊路徑會走到**——但舊書籤、舊連結、使用者自己改網址會。

成因：`frontend/src/App.tsx:52-77` 的 `<Routes>` 沒有 `path="*"` 兜底。react-router 對不上
任何一條就渲染空的 `<Routes>`，`RequireSession` 的 layout 也不在路徑上，於是連導覽列都沒有：
整頁只剩背景色。演練當下驅動去的是 `/brands/<id>/campaigns`（真的路由叫 `/schedule`），
連著四次截圖都是 1280×720 的純色 PNG（`.scratch/drill2/jay/step09-01.png`，本次直接開過）。
小杰因此把整個 step 9 判成「配對功能找不到」，operator 事後才判定 void。

`file:line`：`frontend/src/App.tsx:52-77`（`<Routes>`，沒有 catch-all）、
`frontend/src/App.tsx:79-90`（`RequireSession`，只包在對得上的路由外面）。

做法（未裁決）：加一條 `<Route path="*" element={<NotFound />} />`，內容用既有的
`EmptyState`（同檔 `RequireSession` 已經在用）＋一顆回首頁的按鈕。放在 `RequireSession`
裡面還是外面要挑一次：放裡面沒登入會先被踢去 `/login`（多一跳但不洩漏路徑存在與否），
放外面未登入者也看得到 404。route A，一顆元件。
