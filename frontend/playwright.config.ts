import { defineConfig } from "@playwright/test";

/** 端到端煙霧測試設定（票 shell-04，HANDOFF-shell-slice.md §4）。
 *
 * 一個 spec、一條路徑，沒有 fixture、沒有 page object——這支存在的理由是「切掉
 * `app/ads/` 之後，活下來的 11 支畫面還走得通嗎」，不是逐頁斷言畫面內容。
 *
 * 不自動起伺服器（`webServer`）：後端要 `supabase start` 起來的 Postgres，前端要
 * `npm run build` 過的 `frontend/dist`，兩件事在這台機器上是手動步驟（見
 * HANDOFF-shell-slice.md §8）。要跑這支之前先把後端起好：
 *
 *   uv run python -m uvicorn app.main:app --port 8710
 *   cd frontend && npm run build
 *   cd frontend && npx playwright test
 *
 * 換埠號用 `E2E_BASE_URL=http://localhost:8711 npx playwright test`。
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:8710",
    trace: "retain-on-failure",
  },
});
