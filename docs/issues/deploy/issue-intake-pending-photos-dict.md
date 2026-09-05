# `PENDING_PHOTOS` is a second module-level dict in the same file

Status: before-cloud — found 2026-09-05 while sizing the background-job tickets (08 / 09), which
deliberately do not touch it.

成因：`app/intake/state.py:359` `PENDING_PHOTOS` 是一張模組層 dict，存「上傳了但還沒落地成草稿」
的照片 token → metadata。它不是 job store，所以不歸票 08／09 管，但毛病同型：後端重開就沒了，
雲端多實例時 A 實例收的上傳 B 實例找不到。

影響：比 job 那七支輕。照片的位元組本身已經進 Storage（`app/intake/state.py:388`），dict 裡只有
token 與 metadata，所以掉的是「這批照片還沒歸檔」這個線索，不是檔案本身——使用者要重傳一次，
不會遺失已落地的資料。

`file:line`：`app/intake/state.py:359`、`:388`。

做法（未裁決）：要嘛把 metadata 寫進一張表，要嘛讓 token 自己帶足資訊、從 Storage 的 key 反推。
上雲前值得決一次；今天不擋任何事。
