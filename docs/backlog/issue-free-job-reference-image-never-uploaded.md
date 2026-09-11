# 自由創作的「參考圖」只驗格式，不上傳

2026-09-12，F02 整合審查記下的保留席位。

`frontend/src/components/workbench/FreeJobPage.tsx` 的 參考圖（選填）拖放區會擋掉非
JPG／PNG／WEBP 與超過 10MB 的檔（`ACCEPTED_IMAGE_TYPES`／`MAX_FILE_BYTES`），檔名也會顯示，
但 `file` 只活在元件狀態裡：`handlePrimaryAction()` 建立任務包時完全不帶它，沒有上傳、沒有
storage 列、沒有任何下游讀它。F02-I09/I10 的票面本來寫「using the existing upload path」，實作
只做了前端驗證。

為什麼先不補：今天沒有東西吃得到這張圖。站內出圖是保留席位（ARCHITECTURE.md §5.11，沒有供應商）；
提示詞裡的「見參考商品照」讀的是商品自己的 `official_asset`（§5.10），不是臨時上傳的檔。先上傳等於
在 storage 裡養一批沒有讀者的檔案，還要順帶決定保存期限與刪除時機（`app/core/cleanup.py` 要認得它）。

接的時候一起決定：
- 這張圖是掛在任務包、素材組，還是當成該商品的 `official_asset`？
- 誰會讀它——出圖供應商接上之後的 image-to-image，還是只是給人看的參考？
- 在那之前，拖放區要不要標一句「之後接上」（比照 `image_generation.reason` 那條），
  免得使用者拖完以為送出去了。
