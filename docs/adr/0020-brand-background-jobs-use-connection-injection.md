# 0020：背景工作通知使用連線注入

`app/brand_intelligence/background_job.py` 留在品牌永久層，`notify()` 由呼叫端傳入 `conn`；若搬到 `app/brand_web`，會讓 intake 與 brand_web 形成新的 import 環，因此不搬檔、只移除對 `app.shared.web` 的依賴。
