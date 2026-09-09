# 「產提示詞」灰掉了，四個理由只有一個會說出來

Status: open（drill 2026-09-09，Vivian step 7、小杰 step 7）。**2／3 角色撞到**，
兩人都得出「功能被禁用／可能還沒做完」的結論。operator 用 playwright 複驗小杰那一輪：
採用、再產、關閉、刪除、全部複製全部 enabled，**只有這一顆真的 disabled**。

成因：`frontend/src/components/workbench/BriefDetail.tsx:245-246`
```
const runDisabled =
  busy || localBusy || noSourceForText || !validRequestedCount || brief.closed_at !== null;
```
四個獨立理由（工單還在跑／這次動作還在跑／沒有可用的文案來源／「要幾條提示詞」空白或超出
1–30），但同一顆按鈕的 `title` 只在 `noSourceForText` 時給字（`BriefDetail.tsx:315`），
其餘三種一律沉默——而最常撞到的是最後那一種（欄位預設空白）。

**順帶更正一個流傳中的說法**：不是「兩個數字都填才能按」。「目標張數」
（`targetCount`，`BriefDetail.tsx:287-295`）根本不進 `runDisabled`，只有「要幾條提示詞」進。
照「填目標張數與條數後可按」寫提示會寫出一句假話。

兩人的狀況也不同、畫面卻長一樣：小杰兩個欄位都空（`!validRequestedCount`）；
Vivian 填了 3 與 5，但她剛按過「再產一輪」（`busy`／`localBusy`）。她的原話：
> 「圖片提示詞功能被禁用：可能系統在後台處理前一輪請求。」——她只能用猜的。

`file:line`：`frontend/src/components/workbench/BriefDetail.tsx:245-246`（四個理由）、
`frontend/src/components/workbench/BriefDetail.tsx:311-318`（按鈕與只覆蓋一種的 `title`）、
`frontend/src/components/workbench/BriefDetail.tsx:287-303`（兩個數字欄位）。

做法（未裁決）：按鈕旁邊一行 helper text，依實際命中的那個理由選字——
「先填『要幾條提示詞』（1～30）」／「這一輪還在產，跑完再按」／既有的
「先產文案，或在工單填圖上文字」。一個 `reason` 字串取代現在的 `title`，
不加分支結構（跟 `issue-workbench-count-message-says-image-prompt.md` 同一種一行對照表的做法）。route A。
