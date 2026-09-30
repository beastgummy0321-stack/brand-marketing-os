import { expect, test, type Page } from "@playwright/test";

/** 殼寬回歸閘門（票 u2-fluid-shell-to-1920，ADR 0051 rule 4／Consequences）：16 條路由
 * 在 1280 寬時，殼不能橫向溢出視窗——這是 ADR 0051 量過的那件事（固定 1440px 殼在
 * 1280 時把頂欄控制項推出視窗外）改成流體殼之後，不能再退回去。
 *
 * 量的元素是 `#root`，不是 ADR 0051 Consequences 字面寫的 `document.documentElement`：
 * `tokens.css` 對 `html`／`body`／`#root` 三層都下了 `overflow: hidden`（ADR 0051 背景
 * 段點 2 批評的「只有中間那塊會捲」那個設定，這支票沒有動它）。「prove it red once」
 * 時實測過：把殼硬改回 `w-[2000px]`（比 1280 視窗寬），`document.documentElement.scrollWidth`
 * 量到的還是 1280——`body` 的 `overflow-x:hidden` 先把子元素的溢出吃掉了，沒有傳到
 * `<html>`。`#root` 自己的 `scrollWidth` 不受它自己的 `overflow:hidden` 影響（那只擋畫面
 * 上看不看得到捲軸，量測本身量到的還是實際內容寬度），量到真的 2000。用
 * `document.documentElement` 的版本量到的閘門在這支 app 上是個假閘門，永遠不會紅。
 *
 * 跟 `smoke.spec.ts` 同一套註冊／登入／建品牌手法（陽春路徑：只填名稱，不花錢、不呼叫
 * AI），逐路由 `goto` 量測，不逐頁斷言畫面內容——這支測試只守寬度，內容行為歸
 * `smoke.spec.ts`。
 *
 * `/accept-invite` 不在這 16 條路由裡：它要另一個角色先發邀請信才進得去，
 * `smoke.spec.ts` 也沒有這條路徑可以免費重現。`/login` 因為不需要登入即可到達，量到了。
 * 16 條路由（`App.tsx`）扣掉 `/accept-invite`，共測 15 條。 */
test.use({ viewport: { width: 1280, height: 800 } });

type ApiHeaders = Record<string, string>;

async function api<T>(page: Page, headers: ApiHeaders, method: string, path: string, data?: unknown): Promise<T> {
  const response = await page.request.fetch(path, { method, headers, data });
  const text = await response.text();
  expect(response.ok(), `${method} ${path} failed: ${response.status()} ${text}`).toBeTruthy();
  return text ? (JSON.parse(text) as T) : ({} as T);
}

test("15 條路由（扣 /accept-invite）在 1280 寬不橫向溢出", async ({ page }) => {
  const stamp = Date.now();
  const email = `width-${stamp}@example.com`;
  const password = `width-pw-${stamp}`;
  const brandName = `虛構寬度測試品牌 ${stamp}`;

  async function assertNoOverflow(label: string) {
    const overflow = await page.evaluate(() => ({
      // #root，不是 document.documentElement——見檔頭說明。
      scrollWidth: document.getElementById("root")!.scrollWidth,
      innerWidth: window.innerWidth,
      route: location.pathname,
    }));
    expect(overflow.scrollWidth, `${label}（實際路徑 ${overflow.route}）橫向溢出：` +
      `scrollWidth=${overflow.scrollWidth} > innerWidth=${overflow.innerWidth}`)
      .toBeLessThanOrEqual(overflow.innerWidth);
  }

  // --- /login：不需要登入即可到達 --------------------------------------------
  await page.goto("/app/login");
  await assertNoOverflow("/login");

  // --- 註冊並登入（同 smoke.spec.ts：本機關掉信箱驗證，註冊完當場有 session）；註冊後第一個帶身分的
  // 請求給 API 用的 headers（同 ads-target.spec.ts）-----------------------------------------------
  const overviewRequest = page.waitForRequest((request) =>
    request.url().includes("/api/dashboard/overview") && Boolean(request.headers().authorization),
  );
  await page.getByRole("button", { name: "還沒有帳號？註冊新帳號" }).click();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("密碼").fill(password);
  await page.getByRole("button", { name: "註冊", exact: true }).click();

  // --- / 跨品牌總覽 -----------------------------------------------------------
  await expect(page.getByRole("link", { name: "新增品牌" }).first()).toBeVisible();
  await assertNoOverflow("/");
  const raw = (await overviewRequest).headers();
  const headers: ApiHeaders = Object.fromEntries(
    [["authorization", raw.authorization], ["x-org-id", raw["x-org-id"]]].filter((e): e is [string, string] => Boolean(e[1])),
  );

  // --- /intake/new：建檔精靈第一步，走陽春路徑（只填名稱，不花錢、不呼叫 AI）-----
  await page.getByRole("link", { name: "新增品牌" }).first().click();
  await assertNoOverflow("/intake/new");
  await expect(page.getByLabel("品牌名稱", { exact: true })).toBeVisible();
  await page.getByLabel("品牌名稱", { exact: true }).fill(brandName);

  // --- 投放史二選一（F05-I06）：做在步驟一表單裡，量選完後的表單寬度，再送出 --------
  await page.getByRole("radio", { name: "完全沒投過" }).check();
  await assertNoOverflow("/intake/new（投放史二選一）");
  await page.getByRole("button", { name: "下一步 →" }).click();

  // 沒東西可掃，草稿直接停在精靈第 3 步，網址是 /intake 不是品牌頁根。
  await expect(page).toHaveURL(/\/app\/brands\/brd_.+\/intake/);
  const brandId = new URL(page.url()).pathname.split("/")[3];

  // --- /brands/:brandId/intake ------------------------------------------------
  await assertNoOverflow("/brands/:brandId/intake");

  // --- /brands/:brandId --------------------------------------------------------
  await page.goto(`/app/brands/${brandId}`);
  await assertNoOverflow("/brands/:brandId");

  // --- /brands/:brandId/intake/history（票 past-ads/04，ADR 0067）------------------
  await page.goto(`/app/brands/${brandId}/intake/history`);
  await assertNoOverflow("/brands/:brandId/intake/history");

  // --- /brands/:brandId/library ------------------------------------------------
  await page.goto(`/app/brands/${brandId}/library`);
  await assertNoOverflow("/brands/:brandId/library");

  // --- /brands/:brandId/products（商品頁，F43-I07）：空品牌只有一個空狀態 -------------------
  await page.goto(`/app/brands/${brandId}/products`);
  await expect(page.getByText("還沒有商品")).toBeVisible();
  await assertNoOverflow("/brands/:brandId/products（空）");

  // --- 用商品建檔建一個商品（同 ads-target.spec.ts：建立 → 賣法與價格 → 完成，同步、不花錢），商品頁出現它的卡片；
  // F43-I04：只有建完的賣法能在建立精靈裡選，所以不再用手動新增產品 -----------------------------------
  const intake = `/api/intake/brands/${brandId}/products`;
  const onboarded = await api<{ data: { product_id: string } }>(page, headers, "POST", intake, { name: `寬度測試產品 ${stamp}` });
  await api(page, headers, "PUT", `${intake}/${onboarded.data.product_id}/onboarding/sell-ways`, {
    sell_ways: [{ name: "單品", qty: 1, price: 1580 }],
  });
  await api(page, headers, "POST", `${intake}/${onboarded.data.product_id}/onboarding/complete`);
  const product = { id: onboarded.data.product_id };
  await page.reload();
  await expect(page.getByRole("link", { name: `寬度測試產品 ${stamp}` })).toBeVisible();
  await assertNoOverflow("/brands/:brandId/products");

  // --- 新增商品：商品頁的主按鈕 ---------------------------------------------------------------
  await page.getByRole("link", { name: "＋新增商品" }).click();
  await expect(page).toHaveURL(new RegExp(`/app/brands/${brandId}/products/new$`));
  await assertNoOverflow("/brands/:brandId/products/new");

  // --- /brands/:brandId/products/:productId：舊產品詳情頁照舊，靠網址到達 -----------------------
  await page.goto(`/app/brands/${brandId}/products/${product.id}`);
  await assertNoOverflow("/brands/:brandId/products/:productId");

  // --- /brands/:brandId/orders ------------------------------------------------
  await page.goto(`/app/brands/${brandId}/orders`);
  await assertNoOverflow("/brands/:brandId/orders");

  // --- /brands/:brandId/report ------------------------------------------------
  await page.goto(`/app/brands/${brandId}/report`);
  await assertNoOverflow("/brands/:brandId/report");

  // --- /brands/:brandId/ads（投放中心首頁，F03-I17 取代 /schedule）--------------------
  await page.goto(`/app/brands/${brandId}/ads`);
  await assertNoOverflow("/brands/:brandId/ads");

  // --- /brands/:brandId/ads/campaigns（所有 Campaign 清單，F04-I10）------------------
  await page.goto(`/app/brands/${brandId}/ads/campaigns`);
  await assertNoOverflow("/brands/:brandId/ads/campaigns");

  // --- /brands/:brandId/ads/new：建立活動（F43-I15 瘦身）——第一步選賣法、結果、預算上限，
  // 第二步「系統這樣理解」確認欄位、按「產生策略」才進工作區頁 ----------------------------
  await page.getByRole("link", { name: "建立投放計畫", exact: true }).click();
  await assertNoOverflow("/brands/:brandId/ads/new");
  const shelf = page.getByRole("radiogroup", { name: "要推什麼" });
  await expect(shelf.getByText(`寬度測試產品 ${stamp}`, { exact: true })).toBeVisible();
  await shelf.getByRole("radio", { name: /^單品 NT\$1,580/ }).click();
  await page.getByRole("radio", { name: /^購買/ }).click();
  await page.getByLabel("這個活動最多花").fill("30000");
  await page.getByRole("button", { name: "進階：這期不一樣（平台、受眾、每筆上限、落地頁）", exact: true }).click();
  await expect(page.getByLabel("每筆上限")).toBeVisible();
  await assertNoOverflow("/brands/:brandId/ads/new（進階：這期不一樣 打開）");
  await page.getByRole("button", { name: "下一步：系統理解 →", exact: true }).click();

  // --- /brands/:brandId/ads/new/:campaignId（系統這樣理解）---------------------------
  await expect(page).toHaveURL(new RegExp(`/app/brands/${brandId}/ads/new/[^/]+$`), { timeout: 60000 });
  await expect(page.getByRole("heading", { name: "系統這樣理解" })).toBeVisible();
  await assertNoOverflow("/brands/:brandId/ads/new/:campaignId");
  await page.getByRole("button", { name: "產生策略 →" }).click();

  // --- /brands/:brandId/ads/campaigns/:campaignId ---------------------------------
  await expect(page).toHaveURL(
    new RegExp(`/app/brands/${brandId}/ads/campaigns/[^/?]+\\?tab=strategy`),
    { timeout: 30000 },
  );
  await assertNoOverflow("/brands/:brandId/ads/campaigns/:campaignId");

  // --- ?tab=structure（v10 投放結構樹與各組「進階：編輯這一組」，F30-I08）---------------
  await page.getByRole("button", { name: "投放結構", exact: true }).click();
  await expect(page).toHaveURL(/tab=structure/);
  await assertNoOverflow("/brands/:brandId/ads/campaigns/:campaignId?tab=structure");

  // --- /brands/:brandId/workbench（票 workbench/04，ADR 0068；F02 四個畫面加三條）-------
  await page.goto(`/app/brands/${brandId}/workbench`);
  await assertNoOverflow("/brands/:brandId/workbench");

  // --- /brands/:brandId/workbench/new：走一次真的自由創作，量後面兩條路由才有 pack 可用。
  await page.goto(`/app/brands/${brandId}/workbench/new`);
  await assertNoOverflow("/brands/:brandId/workbench/new");
  await page.getByLabel("告訴 AI 你想創作什麼").fill("寬度測試用的自由創作文字");
  await page.getByRole("button", { name: "建立自由工作" }).click();
  await expect(page.getByRole("button", { name: "確認並生成" })).toBeVisible();
  await page.getByRole("button", { name: "確認並生成" }).click();
  await expect(page).toHaveURL(new RegExp(`/app/brands/${brandId}/workbench/packs/[^/]+$`));

  // --- /brands/:brandId/workbench/packs/:packId ---------------------------------------
  await assertNoOverflow("/brands/:brandId/workbench/packs/:packId");
  const packId = new URL(page.url()).pathname.split("/").pop()!;

  // --- /brands/:brandId/workbench/packs/:packId/sets/:setId ---------------------------
  await page.getByRole("cell", { name: "未生成", exact: true }).locator("..").click();
  await expect(page).toHaveURL(
    new RegExp(`/app/brands/${brandId}/workbench/packs/${packId}/sets/[^/]+$`),
  );
  await assertNoOverflow("/brands/:brandId/workbench/packs/:packId/sets/:setId");

  // --- /inbox -------------------------------------------------------------------
  await page.goto("/app/inbox");
  await assertNoOverflow("/inbox");

  // --- /settings ------------------------------------------------------------------
  await page.goto("/app/settings");
  await assertNoOverflow("/settings");
});
