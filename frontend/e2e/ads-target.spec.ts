import { expect, test } from "@playwright/test";

/** F19-I05／F19-I06 e2e（F28-I01 更新：系統自建的活動一律算購買，成果已預選；存的是唯一的
 * 每筆成本上限）：設定目標頁的最小走查——建一個活動、用 own 依據存一個上限、
 * 存檔後回投放中心、回這頁與整頁重新整理後成果與數字都還在。跟 `smoke.spec.ts` 同一種寫法：每次
 * 跑用一個新帳號＋新品牌，不依賴任何隔離 fixture（那些 `F1[3-9]*_E2E_CONTEXT` 只在設了對應環境
 * 變數才跑，這支任何時候都跑，包含 CI 的 `npm run e2e`）。webServer 已經是
 * `BRAND_OS_LLM_PROVIDER=scripted`（見 playwright.config.ts），建立活動時的 `ads_brief_parse` 呼叫
 * 是罐頭回覆，不是真模型。 */
test("設定目標：own 依據存檔後，回投放中心、重新整理都還看得到同一個數字", async ({ page }) => {
  test.setTimeout(120_000);
  const stamp = Date.now();
  const email = `ads-target-${stamp}@example.com`;
  const password = `ads-target-pw-${stamp}`;
  const brandName = `目標頁驗收品牌 ${stamp}`;

  // --- 註冊、建品牌（陽春路徑，沿用 smoke.spec.ts）---------------------------------------
  await page.goto("/app/login");
  await page.getByRole("button", { name: "還沒有帳號？註冊新帳號" }).click();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("密碼").fill(password);
  await page.getByRole("button", { name: "註冊", exact: true }).click();

  await expect(page.getByRole("link", { name: "新增品牌" }).first()).toBeVisible();
  await page.getByRole("link", { name: "新增品牌" }).first().click();
  await expect(page.getByText("品牌名稱（必填）")).toBeVisible();
  await page.getByLabel("品牌名稱（必填）").fill(brandName);
  await page.getByRole("radio", { name: "完全沒投放過" }).check();
  await page.getByRole("button", { name: "建立品牌並開始初掃" }).click();
  await expect(page).toHaveURL(/\/app\/brands\/brd_.+\/intake/);
  const brandId = new URL(page.url()).pathname.split("/")[3];

  // --- 建一個活動（一句話即可，不选商品／不填限制條件）-------------------------------------
  await page.goto(`/app/brands/${brandId}/ads/new`);
  await page.getByLabel("你這次想做到什麼？").fill("下個月想推主力商品，希望增加購買。");
  await page.getByRole("button", { name: "產生建議", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/app/brands/${brandId}/ads/new/[^/]+$`));
  const campaignId = page.url().split("/").pop()!;

  const targetUrl = `/app/brands/${brandId}/ads/campaigns/${campaignId}/target`;

  // --- 打開設定目標頁：系統自建的活動一律算購買（F28-I01），成果已預選；還沒有上限可存 -------
  await page.goto(targetUrl);
  await expect(page.getByRole("heading", { name: "這個活動的目標", exact: true })).toBeVisible();
  const resultGroup = page.getByRole("group", { name: "看什麼成果", exact: true });
  await expect(resultGroup.getByRole("button", { name: "購買", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText("每次購買最多花多少", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "儲存目標", exact: true })).toBeDisabled();
  // 近 30 天的實際成本不再是依據（F28-I01）。
  await expect(page.getByText("自己近 30 天", { exact: true })).toHaveCount(0);

  // --- 選「自訂」依據，填一個目標值，存檔 -------------------------------------------------
  await page.getByRole("button", { name: /^自訂/ }).click();
  await expect(page.getByText("還差一個數字", { exact: true })).toBeVisible();
  await page.getByLabel("目標每次購買成本", { exact: true }).fill("120");
  const save = page.getByRole("button", { name: "儲存目標", exact: true });
  await expect(save).toBeEnabled();
  const saved = page.waitForResponse(
    (response) => response.url().includes(`/campaigns/${campaignId}/target`) && response.request().method() === "PUT",
  );
  await save.click();
  const savedResponse = await saved;
  expect(savedResponse.ok(), await savedResponse.text()).toBe(true);
  const savedBody = await savedResponse.request().postDataJSON();
  // 成果沒動就不送 result_kind（不把推導值凍結成使用者選擇）；存的是 own 上限 120。
  expect(savedBody.basis).toBe("own");
  expect(savedBody.value).toBe(120);
  expect(savedBody.result_kind).toBeUndefined();

  // --- 存檔後回投放中心（沒有另一個確認畫面，回到列表本身就是「已儲存」的證明）--------------
  await expect(page).toHaveURL(new RegExp(`/app/brands/${brandId}/ads$`));

  // --- 回這頁：同一個成果與數字還在；整頁重新整理（不是前端快取）也還在 ----------------------
  // 「自訂」卡本身也照 API 的 own_value 秀一次同一個數字（repair #5），所以畫面上會有兩個
  // "120"：卡片上那個＋下面「目前判斷用的目標線」那個。用 .last() 專指後者，跟前一版斷言
  // 的意圖一樣（存進去的數字＝目前拿來判斷的目標線）。
  await page.goto(targetUrl);
  await expect(resultGroup.getByRole("button", { name: "購買", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText("每次購買最多花多少", { exact: true })).toBeVisible();
  await expect(page.getByText("120", { exact: true }).last()).toBeVisible();
  await expect(page.getByText("目前判斷用的目標線", { exact: true })).toBeVisible();
  await page.reload();
  await expect(resultGroup.getByRole("button", { name: "購買", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText("120", { exact: true }).last()).toBeVisible();
});
