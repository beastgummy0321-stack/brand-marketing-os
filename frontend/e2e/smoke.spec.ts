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

  // --- 品牌頁：外殼切片後是品牌標題，右上角是進檔期的入口（缺陷 3）-------------
  await expect(page).toHaveURL(/\/app\/brands\/brd_/);
  await expect(page.getByRole("heading", { name: brandName })).toBeVisible();
  await expect(page.getByRole("link", { name: "排這期的檔期" })).toBeVisible();

  const brandId = new URL(page.url()).pathname.split("/")[3];

  // --- 檔期：缺陷 3 —— 品牌頁要有真的入口，不是只能手打網址 -------------------
  await page.getByRole("link", { name: "排這期的檔期" }).click();
  await expect(page).toHaveURL(new RegExp(`/app/brands/${brandId}/schedule$`));
  await expect(page.getByRole("heading", { name: "檔期", exact: true })).toBeVisible();

  // --- 產品 -----------------------------------------------------------------
  await page.goto(`/app/brands/${brandId}/products`);
  await expect(page.getByRole("heading", { name: "產品", exact: true })).toBeVisible();

  // --- 訂單 -----------------------------------------------------------------
  await page.goto(`/app/brands/${brandId}/orders`);
  await expect(page.getByRole("heading", { name: "訂單與顧客" })).toBeVisible();

  // --- 品牌智庫：上傳一張圖，而且那張圖真的畫得出來 --------------------------
  // 第 ⑥ 片（2026-08-30）加。上傳走的是真的 Supabase Storage（ADR 0043），所以這一段
  // 順便證明「存得進去、讀得回來」；但它真正守的是**縮圖有沒有真的顯示**——
  // `naturalWidth > 0` 才算數，`toBeVisible()` 不算：破圖的 <img> 也是可見的。
  // 這條路以前沒有任何測試走過，於是「圖片路由要求登入、<img> 不會帶權杖」這個 401
  // 在畫面上安靜地退化成一個小圖示，撐到 2026-08-30 手動驗收才被抓到。
  await page.goto(`/app/brands/${brandId}/library`);
  await page.getByRole("button", { name: "官方素材" }).click();
  await page.getByRole("button", { name: "上傳素材" }).click();
  await page.locator('input[type="file"]').setInputFiles({
    name: "smoke.png",
    mimeType: "image/png",
    // 1x1 紅點 PNG：夠小、是合法的 PNG，瀏覽器解得開才會有 naturalWidth。
    buffer: Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
      "base64",
    ),
  });
  await page.getByLabel("種類").selectOption("logo");
  await page.getByRole("button", { name: "上傳這個素材" }).click();

  const thumbnail = page.locator('img[alt="Logo"]').first();
  await expect(thumbnail).toBeVisible();
  await expect
    .poll(() => thumbnail.evaluate((img) => (img as HTMLImageElement).naturalWidth))
    .toBeGreaterThan(0);

  // --- 開帳讀歷史（票 S2）-----------------------------------------------------
  // D0-b（S2-DESIGN.md，使用者 2026-08-31 裁定）：這支帳號是每次都重新註冊的全新帳號，
  // 沒有 Meta token、沒有任何成效資料，不可能有一筆真的 onboarding_read 判讀存在，所以
  // 這裡只證明路由掛得上、畫面亮得出來、誠實的空狀態出現；「勾一條結論→ 剛好一筆帳本
  // 紀錄」改由後端測試直接打真的 HTTP 路由證明（done-check 1-3 本來就是那樣做的）。
  await page.goto(`/app/brands/${brandId}/onboarding-read`);
  await expect(page.getByRole("heading", { name: "開帳讀歷史", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "還沒有綁定 Meta 廣告帳戶" })).toBeVisible();
});
