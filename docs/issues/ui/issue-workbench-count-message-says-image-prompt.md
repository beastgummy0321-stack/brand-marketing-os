# 影片腳本支數超出範圍時，API 錯誤訊息講的是「圖片提示詞張數」

Status: open（2026-09-09 workbench ticket 06 審查備註，不擋出貨）。

成因：`app/workbench/routes.py:63,118` 的 `count_out_of_range` 對照表寫死一句「圖片提示詞張數需介於 1 到 30 之間。」，
`video_script` 的合法範圍是 1～5，直接打 API 傳壞值會拿到講錯部位的句子（畫面自己的表單驗證擋住了，使用者看不到）。

做法：route A，錯誤訊息依 part 選字：圖片提示詞 1～30、影片腳本 1～5。一行對照表，不加分支。
