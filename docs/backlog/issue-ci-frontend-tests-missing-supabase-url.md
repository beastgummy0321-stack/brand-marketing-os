# CI 前端 `npm test` 缺 VITE_SUPABASE_URL，13 個測試檔載入即失敗

Status: 2026-09-14 F06 推上 saas 後查 CI 看到；F06 之前就紅（ff4b17e 同樣錯誤）。

事實：
- GitHub Actions run 34842321202（commit 2063862）：`backend` 綠、`frontend` 紅在 `Run npm test`。
- 失敗原因：「supabaseUrl is required」出現 25 次；13 個測試檔在載入階段就掛（ads／intake／workbench 各頁測試，
  凡是 import 到會建 Supabase client 的模組都中）；真的有跑到的 47 個測試全過。
- `.github/workflows/ci.yml:57-62` 只在 `backend` job 寫入 `VITE_SUPABASE_URL`／`VITE_SUPABASE_ANON_KEY`；
  `frontend` job（:76 起，:94 `npm test`）沒有這兩個變數。本機會過是因為有 `.env`。
- 前一次（ff4b17e）backend 的 `e2e smoke` 也紅（當時 e2e 接真 codex，CI 沒有 codex）；F06-I05 腳本化 AI 之後 backend 已綠。

待定：frontend job 補一個假的 `VITE_SUPABASE_URL`（測試不連線，只需非空），還是讓 Supabase client 在測試環境延後建立。
前者一行、後者是根因（模組載入就建 client），先實測哪幾個模組在 import 時就呼叫 `createClient`。
