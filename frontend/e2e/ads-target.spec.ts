import { expect, test, type Page } from "@playwright/test";

/** F28-I09 e2e: the cap is set in the strategy tab's 「一個上限」 card (the old target page's address redirects there).
 * Walks the card's real states on a fresh account + brand: no product → pick one in the fold; a product without a cost
 * (沒有商品成本 + 去填商品成本); the cost filled → 暫用打平 520 after a reload; an own cap of 120 saved through
 * `PUT .../target` and still there after a full reload. Same style as `smoke.spec.ts`: runs every time (CI
 * `npm run e2e`), the webServer's scripted provider answers `ads_brief_parse`, no live model or platform account. */

type ApiHeaders = Record<string, string>;

async function api<T>(page: Page, headers: ApiHeaders, method: string, path: string, data?: unknown): Promise<T> {
  const response = await page.request.fetch(path, { method, headers, data });
  const text = await response.text();
  expect(response.ok(), `${method} ${path} failed: ${response.status()} ${text}`).toBeTruthy();
  return text ? (JSON.parse(text) as T) : ({} as T);
}

test("一個上限：選商品、沒有成本、暫用打平、自己的上限存檔後重新整理都還在", async ({ page }) => {
  test.setTimeout(120_000);
  const stamp = Date.now();

  // --- 註冊、建品牌（沿用 smoke.spec.ts）；註冊後第一個帶身分的請求給 API 用的 headers ---------------------
  const overviewRequest = page.waitForRequest((request) =>
    request.url().includes("/api/dashboard/overview") && Boolean(request.headers().authorization),
  );
  await page.goto("/app/login");
  await page.getByRole("button", { name: "還沒有帳號？註冊新帳號" }).click();
  await page.getByLabel("Email").fill(`ads-target-${stamp}@example.com`);
  await page.getByLabel("密碼").fill(`ads-target-pw-${stamp}`);
  await page.getByRole("button", { name: "註冊", exact: true }).click();
  await expect(page.getByRole("link", { name: "新增品牌" }).first()).toBeVisible();
  const raw = (await overviewRequest).headers();
  const headers: ApiHeaders = Object.fromEntries(
    [["authorization", raw.authorization], ["x-org-id", raw["x-org-id"]]].filter((e): e is [string, string] => Boolean(e[1])),
  );
  await page.getByRole("link", { name: "新增品牌" }).first().click();
  await page.getByLabel("品牌名稱（必填）").fill(`上限驗收品牌 ${stamp}`);
  await page.getByRole("radio", { name: "完全沒投放過" }).check();
  await page.getByRole("button", { name: "建立品牌並開始初掃" }).click();
  await expect(page).toHaveURL(/\/app\/brands\/brd_.+\/intake/);
  const brandId = new URL(page.url()).pathname.split("/")[3];

  // A product with no economics yet (手動新增：同步、不花錢).
  const product = await api<{ id: string }>(page, headers, "POST", `/api/products/brands/${brandId}`, { name: "晨光隨行杯 500ml 通勤款" });

  // --- 建一個沒有商品的活動（一句話的建立 API；F30-I05 的建立精靈一定要選商品，這裡要測「沒有商品」的分支）------
  const { campaign } = await api<{ campaign: { id: string } }>(page, headers, "POST", `/api/ads/brands/${brandId}/campaigns`, {
    goal_text: "下個月想推主力商品，希望增加購買。",
  });
  const campaignId = campaign.id;

  // --- 舊的設定目標網址轉到策略分頁 --------------------------------------------------------------------
  await page.goto(`/app/brands/${brandId}/ads/campaigns/${campaignId}/target`);
  await expect(page).toHaveURL(new RegExp(`/app/brands/${brandId}/ads/campaigns/${campaignId}\\?tab=strategy$`));
  await expect(page.getByRole("heading", { name: "一個上限", exact: true })).toBeVisible();
  const capInput = page.getByLabel("每賣一筆最多花多少（上限）", { exact: true });
  await expect(capInput).toBeVisible();
  await expect(page.getByText("沒設上限，先不分等級", { exact: true })).toBeVisible();

  // --- 沒有商品：在收合裡選商品（成果是系統自建的「購買」，已預選、不重送）-------------------------------
  await page.getByRole("button", { name: "選商品與成果（算打平要用）", exact: true }).click();
  await expect(page.getByRole("button", { name: "購買", exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("combobox").selectOption(product.id);
  const picked = page.waitForResponse((r) => r.url().endsWith(`/campaigns/${campaignId}/target`) && r.request().method() === "PUT");
  await page.getByRole("button", { name: "儲存", exact: true }).click();
  const pickedBody = (await picked).request().postDataJSON();
  expect(pickedBody.product_id).toBe(product.id);
  expect(pickedBody.result_kind).toBeUndefined();

  // --- 商品沒有成本：誠實說沒有，連到該商品的經濟數字 ------------------------------------------------------
  await expect(page.getByText("沒有商品成本", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "去填商品成本", exact: true })).toHaveAttribute(
    "href", `/app/brands/${brandId}/products/${product.id}?tab=economics-view`,
  );

  // --- 補上成本（售價 1,580 − 成本 1,000 − 運費 60 = 打平 520）後重新整理：暫用打平 -----------------------
  await api(page, headers, "POST", `/api/products/brands/${brandId}/products/${product.id}/economics`, {
    selling_price: 1580, fixed_cost: 0, unit_variable_cost: 1000, shipping_cost: 60, currency: "TWD", confirmed_by: "e2e",
  });
  await page.reload();
  await expect(page.getByText("NT$520", { exact: true })).toBeVisible();
  await expect(page.getByText("暫用打平", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "就用 520", exact: true })).toBeVisible();

  // --- 設定自己的上限 120，存檔（PUT target，own，帶版本號）--------------------------------------------
  await page.getByRole("button", { name: "設定自己的上限", exact: true }).click();
  await capInput.fill("120");
  await expect(page.getByText("比打平 520 低 400・ROAS 參考 13.17", { exact: true })).toBeVisible();
  const saved = page.waitForResponse((r) => r.url().endsWith(`/campaigns/${campaignId}/target`) && r.request().method() === "PUT");
  await page.getByRole("button", { name: "儲存上限", exact: true }).click();
  const savedResponse = await saved;
  expect(savedResponse.ok(), await savedResponse.text()).toBe(true);
  const savedBody = savedResponse.request().postDataJSON();
  expect(savedBody).toMatchObject({ basis: "own", value: 120 });
  expect(typeof savedBody.expected_revision).toBe("number");
  await expect(page.getByText("NT$120", { exact: true })).toBeVisible();
  await expect(page.getByText("自己填", { exact: true })).toBeVisible();

  // --- 整頁重新整理（不是前端快取）也還在 ------------------------------------------------------------------
  await page.reload();
  await expect(page.getByText("NT$120", { exact: true })).toBeVisible();
  await expect(page.getByText("ROAS 參考 13.17・打平 520", { exact: true })).toBeVisible();
});
