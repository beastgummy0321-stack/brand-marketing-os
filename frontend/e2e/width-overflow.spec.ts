import { expect, test, type Page } from "@playwright/test";
import { strategyFixture } from "../src/components/ads/strategy/strategyEvidence.fixtures";
import {libraryEvidenceFixture, libraryOptionsFixture, libraryShellFixture} from "../src/components/ads/learnings/learningEvidence.fixtures";

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

for (const width of [1024, 1920]) {
  test(`F53 library ${width}: source keyboard, retained scope, null/zero, cold and read recovery`, async ({page}, info) => {
    await page.setViewportSize({width, height: 1200});
    await page.goto("/app/login");
    await page.getByLabel("Email").fill("123@example.com");
    await page.getByLabel("密碼").fill("123456");
    await page.getByRole("button", {name: "登入", exact: true}).click();
    await page.waitForURL(url => !url.pathname.includes("login"));
    const data = libraryEvidenceFixture();
    const long = "下班後夜跑、步行通勤與戶外活動的完整商品情境名稱".repeat(8);
    data.evidence_context.items[0].display_text = long;
    data.evidence_context.items[0].scope.product_label = long;
    data.evidence_context.items[0].contrary_count = 1;
    data.evidence_context.items[0].use_state = "revalidation";
    data.evidence_context.items[0].reason_labels = ["已有反向觀察，需重新核對。"];
    const picks = structuredClone(libraryOptionsFixture);
    picks.products[0].name = long;
    picks.products.push({...picks.products[0], id: "prd_second", name: "第二商品 · 單件"});
    let fail = false;
    let release: (() => void) | null = null;
    let delay = false;
    let cold = false;
    const errors: string[] = [];
    const writes: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.route("**/api/**", route => {
      if (route.request().method() !== "GET") {writes.push(route.request().url()); return route.abort();}
      return route.continue();
    });
    await page.route("**/api/dashboard/overview", route => route.fulfill({json: {data: [{brand_id: "brd_f53_ui", brand_name: "夜行裝備", health: "green", revenue_this_month: null, revenue_mom_pct: null, next_step: null}], generated_at: "2026-10-08T00:00:00Z"}}));
    await page.route("**/api/jobs/active", route => route.fulfill({json: {data: [], total: 0, other_count: 0, done_today: 0, failed_today: 0, generated_at: "2026-10-08T00:00:00Z", worker_alive: true, stalled: false}}));
    await page.route("**/api/library/brands/brd_f53_ui", route => route.fulfill({json: {data: libraryShellFixture, generated_at: "2026-10-08T00:00:00Z"}}));
    await page.route("**/api/ads/brands/brd_f53_ui/new-campaign/options", route => route.fulfill({json: picks}));
    await page.route("**/api/ads/brands/brd_f53_ui/coordinate-learnings*", async route => {
      const id = new URL(route.request().url()).searchParams.get("sell_way_id");
      if (id && delay) await new Promise<void>(resolve => {release = resolve;});
      if (id && fail) return route.fulfill({status: 502, json: {error: {message: "來源暫時無法讀取"}}});
      const response = structuredClone(data);
      if (id) {response.evidence_context.scope_product_id = id; response.next = null; response.campaigns = [];}
      if (cold) {response.evidence_context.items = []; response.evidence_context.eligible_count = 0; response.campaigns = []; response.next = null;}
      return route.fulfill({json: response});
    });
    await page.goto("/app/brands/brd_f53_ui/library?tab=ads-learnings");
    const scene = page.locator("[data-slot=learning-screen]");
    await expect(page.getByRole("link", {name: "用可參考資料規劃下一期 →"})).toBeVisible();
    await expect(scene.getByText("本商品不適用。", {exact: true})).toBeVisible();
    await expect(scene.getByText("已有反向觀察，需重新核對。", {exact: true})).toBeVisible();
    for (const node of [page.locator("#root"), page.locator("body"), scene, page.locator("[data-slot=qualified-learning-list]")]) {
      expect(await node.evaluate(element => element.scrollWidth)).toBeLessThanOrEqual(await node.evaluate(element => element.clientWidth));
    }
    const bounds = await scene.evaluate(node => {
      const r = node.getBoundingClientRect();
      return {left: r.left, right: r.right, cards: Array.from(node.querySelectorAll(".surface, [data-slot=library-learning-row], [data-slot=learning-evidence] p")).map(card => {const c = card.getBoundingClientRect(); return {left: c.left, right: c.right};})};
    });
    for (const card of bounds.cards) {expect(card.left).toBeGreaterThanOrEqual(bounds.left - 1); expect(card.right).toBeLessThanOrEqual(bounds.right + 1);}
    await expect(page.getByRole("button", {name: "每期廣告排名"})).toHaveAttribute("aria-expanded", "false");
    const longSourceTrigger = scene.getByRole("button", {name: "查看 →"}).first();
    await longSourceTrigger.click();
    const longSource = page.getByRole("dialog", {name: "經驗來源與適用範圍"});
    await longSource.getByRole("button", {name: "完整來源與限制"}).click();
    expect(await longSource.evaluate(node => node.scrollWidth)).toBeLessThanOrEqual(await longSource.evaluate(node => node.clientWidth));
    await expect(longSource.getByText("已有反向觀察，需重新核對。", {exact: true})).toBeVisible();
    await page.screenshot({path: info.outputPath(`library-source-long-complete-${width}.png`), fullPage: true});
    await page.keyboard.press("Escape");
    await expect(longSource).toHaveCount(0);
    await expect(longSourceTrigger).toBeFocused();
    const sourceTrigger = scene.getByRole("button", {name: "查看 →"}).nth(3);
    await sourceTrigger.focus();
    await expect(sourceTrigger).toBeFocused();
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("dialog", {name: "經驗來源與適用範圍"});
    await expect(dialog.getByText("樣本尚未完整核實", {exact: true})).toBeVisible();
    for (let i = 0; i < 8; i++) {await page.keyboard.press("Tab"); expect(await dialog.evaluate(node => node.contains(document.activeElement))).toBe(true);}
    await page.screenshot({path: info.outputPath(`library-source-null-${width}.png`), fullPage: true});
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(sourceTrigger).toBeFocused();
    const zeroSourceTrigger = scene.getByRole("button", {name: "查看 →"}).nth(4);
    await zeroSourceTrigger.click();
    await expect(dialog.getByText("0 筆", {exact: true})).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(zeroSourceTrigger).toBeFocused();
    await page.getByRole("button", {name: "下一期商品範圍"}).click();
    await page.getByRole("combobox", {name: "選擇商品"}).selectOption("prd_second");
    await expect(page.getByRole("link", {name: "用可參考資料規劃下一期 →"})).toHaveAttribute("href", "/app/brands/brd_f53_ui/ads/new?sell_way=prd_second");
    delay = true;
    await page.getByRole("button", {name: "重新讀取 ↻"}).click();
    await expect(page.getByRole("status")).toContainText("正在讀取");
    await expect(scene.locator("[data-slot=library-learning-row]")).toHaveCount(6);
    await page.screenshot({path: info.outputPath(`library-loading-${width}.png`), fullPage: true});
    await expect.poll(() => Boolean(release)).toBe(true);
    delay = false; fail = true; release!();
    await expect(page.getByRole("alert")).toContainText("保留同商品上次讀取");
    await expect(page.getByRole("combobox", {name: "選擇商品"})).toHaveValue("prd_second");
    await page.screenshot({path: info.outputPath(`library-error-retained-draft-${width}.png`), fullPage: true});
    fail = false;
    await page.getByRole("button", {name: "重新讀取", exact: true}).click();
    await expect(page.getByRole("link", {name: "用可參考資料規劃下一期 →"})).toHaveAttribute("href", "/app/brands/brd_f53_ui/ads/new?sell_way=prd_second");
    cold = true; await page.reload();
    await page.getByRole("button", {name: "下一期商品範圍"}).click();
    await page.getByRole("combobox", {name: "選擇商品"}).selectOption("prd_fixture");
    await expect(page.getByText("還沒有學習紀錄", {exact: true})).toBeVisible();
    await page.screenshot({path: info.outputPath(`library-cold-${width}.png`), fullPage: true});
    await page.getByRole("link", {name: "用可參考資料規劃下一期 →"}).click();
    await expect(page).toHaveURL(/\/app\/brands\/brd_f53_ui\/ads\/new\?sell_way=prd_fixture$/);
    expect(errors).toEqual([]); expect(writes).toEqual([]);
  });
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
    sell_ways: [{ name: "單品", price: 1580 }],
  });
  // F50 Contract R: a product with zero customer groups is not ready (not pickable, 完成 refused) — one group first.
  await api(page, headers, "PUT", `${intake}/${onboarded.data.product_id}/onboarding/who`, {
    groups: [{ who: "通勤上班族", pain_keys: ["effort"] }],
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
  await shelf.getByRole("radio", { name: /^單品 1,580 TWD/ }).click();
  await page.getByRole("radio", { name: /^購買/ }).click();
  await page.getByLabel("這個活動最多花").fill("30000");
  // F46-I08: 平台／每筆上限 sit in 「期間、預算與平台」 (with source tags); the fold keeps 受眾 and 落地頁.
  await expect(page.getByLabel("每筆上限")).toBeVisible();
  await assertNoOverflow("/brands/:brandId/ads/new（進階：這期不一樣 收合）");
  await page.getByRole("button", { name: "進階：這期不一樣（受眾、落地頁）", exact: true }).click();
  await expect(page.getByLabel("落地頁")).toBeVisible();
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

/** Local fixture receipts: all product writes are intercepted before the real API. */
for (const width of [1024, 1920]) {
  test(`F53 strategy basis ${width}: long names, source focus, null/zero and guarded approval`, async ({page}, info) => {
    await page.setViewportSize({width, height: 1200});
    await page.goto("/app/login");
    await page.getByLabel("Email").fill("123@example.com");
    await page.getByLabel("密碼").fill("123456");
    await page.getByRole("button", {name: "登入", exact: true}).click();
    await page.waitForURL(url => !url.pathname.includes("login"));
    const c = strategyFixture();
    const long = "下班後直接出門夜跑與步行通勤、需要反光及輕量穿著的上班族".repeat(4);
    c.budget_basis_json.strategy!.decision!.slots[0].display!.customer_group_label = long;
    c.budget_basis_json.basis!.evidence_context.scope_label = "反光夜跑背心・長商品名稱與賣法完整保留".repeat(5);
    c.budget_basis_json.basis!.learnings[0].evidence.sample = {result_events: null, sufficient: null};
    c.budget_basis_json.basis!.learnings[1].evidence.sample = {result_events: 0, sufficient: false};
    const errors: string[] = [];
    const requests: {expected_revision: string; operation_id: string}[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.route("**/api/**", route => route.request().method() === "GET" ? route.continue() : route.abort());
    await page.route("**/api/dashboard/overview", route => route.fulfill({json: {data: [{brand_id: "brd_f53_ui", brand_name: "夜行裝備", health: "green", revenue_this_month: null, revenue_mom_pct: null, next_step: null}], generated_at: "2026-10-08T00:00:00Z"}}));
    await page.route("**/api/jobs/active", route => route.fulfill({json: {data: [], total: 0, other_count: 0, done_today: 0, failed_today: 0, generated_at: "2026-10-08T00:00:00Z", worker_alive: true, stalled: false}}));
    await page.route("**/api/ads/brands/brd_f53_ui/campaigns/cmp_f53_ui", route => route.fulfill({json: {campaign: c}}));
    await page.route("**/api/ads/brands/brd_f53_ui/campaigns/cmp_f53_ui/workspace", route => route.fulfill({json: {stage: {key: "plan", done: []}, pending_count: 0, delivery: null, daily_budget: null, active_ads: 0, can_support: null, next_sync_at: null, missing_days: [], totals: null, draft: {cap_set: true, budget_set: true, slots_ready: 0, slots_total: 0, launch_checked: 0, launch_total: 0}}}));
    await page.route("**/api/ads/brands/brd_f53_ui/campaigns/cmp_f53_ui/plan", async route => {
      requests.push(route.request().postDataJSON());
      await route.fulfill({status: 502, json: {error: {message: "尚未收到可確認的結果，請沿用原操作重試。", code: "unknown_result"}}});
    });
    await page.goto("/app/brands/brd_f53_ui/ads/campaigns/cmp_f53_ui?tab=strategy");
    await expect(page.getByRole("heading", {name: "這期怎麼安排", exact: true})).toBeVisible();
    await expect(page.getByText(long, {exact: true})).toBeVisible();
    const rootWidth = await page.locator("#root").evaluate(root => root.scrollWidth);
    expect(rootWidth).toBeLessThanOrEqual(width);
    const scene = page.locator("[data-slot=strategy-screen]");
    const body = scene.locator("[data-slot=strategy-body]");
    expect(await page.locator("body").evaluate(node => node.scrollWidth)).toBeLessThanOrEqual(width);
    expect(await page.locator("html").evaluate(node => node.scrollWidth)).toBeLessThanOrEqual(width);
    expect(await body.evaluate(node => node.scrollWidth)).toBeLessThanOrEqual(await body.evaluate(node => node.clientWidth));
    const bounds = await scene.evaluate(node => {
      const sceneRect = node.getBoundingClientRect();
      const bar = node.querySelector("[data-slot=action-bar]")!;
      const barRect = bar.getBoundingClientRect();
      return {sceneLeft: sceneRect.left, sceneRight: sceneRect.right, barLeft: barRect.left, barRight: barRect.right,
        cards: Array.from(node.querySelectorAll(".surface, [data-slot=allocation-row]")).map(card => {
          const r = card.getBoundingClientRect(); return {left: r.left, right: r.right};
        })};
    });
    // The shared bar intentionally fills the parent's 22px/28px padding, within the viewport.
    const inset = width >= 1280 ? 28 : 22;
    expect(bounds.barLeft).toBeGreaterThanOrEqual(bounds.sceneLeft - inset - 1);
    expect(bounds.barRight).toBeLessThanOrEqual(bounds.sceneRight + inset + 1);
    expect(bounds.barLeft).toBeGreaterThanOrEqual(0); expect(bounds.barRight).toBeLessThanOrEqual(width);
    for (const card of bounds.cards) {
      expect(card.left).toBeGreaterThanOrEqual(bounds.sceneLeft - 1);
      expect(card.right).toBeLessThanOrEqual(bounds.sceneRight + 1);
    }
    for (const label of ["這輪想確認什麼", "還有哪些未知", "未用於提案的資料"]) await expect(page.getByRole("button", {name: label, exact: true})).toHaveAttribute("aria-expanded", "false");
    const trigger = page.getByRole("button", {name: "查看依據 →", exact: true});
    await trigger.focus(); await page.keyboard.press("Enter");
    await expect(page.getByRole("dialog", {name: "策略依據", exact: true})).toBeVisible();
    await page.getByRole("button", {name: "查看來源與限制 →", exact: true}).first().click();
    const source = page.getByRole("dialog", {name: "經驗來源與適用範圍", exact: true});
    await expect(source.getByText("樣本尚未完整核實", {exact: true})).toBeVisible();
    await expect(source.getByText(long, {exact: true})).toBeVisible();
    for (let i = 0; i < 8; i++) { await page.keyboard.press("Tab"); expect(await source.evaluate(dialog => dialog.contains(document.activeElement))).toBe(true); }
    expect(await source.evaluate(node => node.scrollWidth)).toBeLessThanOrEqual(await source.evaluate(node => node.clientWidth));
    await page.screenshot({path: info.outputPath(`source-${width}.png`), fullPage: true});
    await page.keyboard.press("Escape"); await expect(source).not.toBeVisible(); await expect(trigger).toBeFocused();
    await trigger.click(); await page.getByRole("button", {name: "查看來源與限制 →", exact: true}).nth(1).click();
    await expect(page.getByRole("dialog").getByText("0 筆", {exact: true})).toBeVisible();
    await page.keyboard.press("Escape");
    const confirm = page.getByRole("button", {name: "確認策略，查看投放結構 →", exact: true});
    await confirm.click(); await expect(page.getByText("尚未收到可確認的結果，請沿用原操作重試。", {exact: true})).toBeVisible();
    await confirm.click(); await expect.poll(() => requests.length).toBe(2);
    expect(requests[0]).toEqual(requests[1]); expect(requests[0].expected_revision).toBe("decision-fixture");
    expect(requests[0].operation_id).toMatch(/^[0-9a-f-]{36}$/);
    await expect(page).toHaveURL(/tab=strategy/); expect(errors).toEqual([]);
  });
}
