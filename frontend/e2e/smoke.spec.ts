import { expect, test } from "@playwright/test";

/** 全站煙霧測試（票 shell-04，HANDOFF-shell-slice.md §4）。
 *
 * 一條路徑走完活下來的主要畫面：註冊登入 → 跨品牌總覽 → 建檔精靈建一個品牌 →
 * 品牌頁 → 產品 → 訂單。這支證明的是「切掉 `app/ads/` 之後畫面還走得通」，
 * 不逐頁斷言內容——畫面內容的細節不歸它管（工作流規範：畫面行為只給一支
 * 端到端煙霧測試，不寫單元測試）。
 *
 * 它取代了 `app/tests/test_architecture_boundaries.py` 裡兩支昂貴又脆的掃描
 * （`ClipboardHonestyScanTest`／`ReviewStepSettleRefetchWiringTest`）——那兩支
 * 斷言的都是畫面行為，存在的唯一原因是這個專案沒有煙霧測試。
 *
 * 不花錢：品牌只填名稱、描述與網址留空，`app/intake/state.start_or_quick()` 走
 * 「陽春路徑」不建草稿、不呼叫 AI。改動這支時務必維持這個性質。
 */
test("走完切片後活下來的主要畫面", async ({ page }) => {
  // 每次跑用一個新帳號：本機 Supabase 關掉了信箱驗證（supabase/config.toml
  // `enable_confirmations = false`），註冊完當場就有 session，不必收信。
  const stamp = Date.now();
  const email = `smoke-${stamp}@example.com`;
  const password = `smoke-pw-${stamp}`;
  const brandName = `虛構煙霧測試品牌 ${stamp}`;

  // --- 註冊並登入 -----------------------------------------------------------
  await page.goto("/app/login");
  await page.getByRole("button", { name: "還沒有帳號？註冊新帳號" }).click();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("密碼").fill(password);
  await page.getByRole("button", { name: "註冊", exact: true }).click();

  // --- 跨品牌總覽 -----------------------------------------------------------
  await expect(page.getByRole("link", { name: "新增品牌" }).first()).toBeVisible();

  // --- 建檔精靈：只填品牌名稱，走不花錢的陽春路徑 ---------------------------
  await page.getByRole("link", { name: "新增品牌" }).first().click();
  await expect(page.getByText("品牌名稱（必填）")).toBeVisible();
  await page.getByLabel("品牌名稱（必填）").fill(brandName);
  await page.getByRole("button", { name: "建立品牌並開始初掃" }).click();

  // --- 品牌頁：外殼切片後是品牌標題＋「本期還沒有方案」空態 -----------------
  await expect(page).toHaveURL(/\/app\/brands\/brd_/);
  await expect(page.getByRole("heading", { name: brandName })).toBeVisible();
  await expect(page.getByText("本期還沒有方案")).toBeVisible();

  const brandId = new URL(page.url()).pathname.split("/")[3];

  // --- 產品 -----------------------------------------------------------------
  await page.goto(`/app/brands/${brandId}/products`);
  await expect(page.getByRole("heading", { name: "產品", exact: true })).toBeVisible();

  // --- 訂單 -----------------------------------------------------------------
  await page.goto(`/app/brands/${brandId}/orders`);
  await expect(page.getByRole("heading", { name: "訂單與顧客" })).toBeVisible();
});
