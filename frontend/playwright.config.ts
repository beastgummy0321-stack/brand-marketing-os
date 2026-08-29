import { defineConfig } from "@playwright/test";

/** 端到端煙霧測試設定（票 shell-04，HANDOFF-shell-slice.md §4；票 07-0 改成一鍵）。
 *
 * 一個 spec、一條路徑，沒有 fixture、沒有 page object——這支存在的理由是「切掉
 * `app/ads/` 之後，活下來的 11 支畫面還走得通嗎」，不是逐頁斷言畫面內容。
 *
 * 一個指令跑完（票 07-0）：`cd frontend && npm run e2e` 會 build 前端、起一個
 * 只給測試用的後端、跑完把它關掉。前提只剩一個：`supabase start` 已經起著。
 *
 * 後端起在 8720，跟人在用的 8710 分開：你自己開著行銷系統時也能跑閘門。
 * 故意不重用已經在跑的 server（`reuseExistingServer: false`）——閘門要測的是這次
 * 改的程式碼，重用一個放著沒關的舊 server 會讓閘門說謊。
 *
 * 要對著自己已經起好的 server 跑（例如手動除錯）：
 *
 *   E2E_BASE_URL=http://localhost:8710 npx playwright test
 *
 * 設了 `E2E_BASE_URL` 就不自己起 server，也不 build——你起的你自己負責。
 */
const E2E_PORT = 8720;
const externalServer = process.env.E2E_BASE_URL;

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: externalServer ?? `http://localhost:${E2E_PORT}`,
    trace: "retain-on-failure",
  },
  webServer: externalServer
    ? undefined
    : {
        // cwd 預設是這個設定檔所在的資料夾（frontend/），後端要從 repo 根目錄起。
        command: `uv run python -m uvicorn app.main:app --port ${E2E_PORT}`,
        cwd: "..",
        port: E2E_PORT,
        reuseExistingServer: false,
        // 冷啟動要等連線池接上 Postgres；`啟動行銷系統.bat` 也是等到 60 秒。
        timeout: 120_000,
      },
});
