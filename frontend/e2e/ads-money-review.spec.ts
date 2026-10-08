import { expect, test, type Page } from "@playwright/test";
import { mkdir, readFile } from "node:fs/promises";
import path from "node:path";
import { MONTH_BRAND, MONTH, PREVIOUS, monthEvidence, MONTH_RULES } from "../src/components/ads/month/monthEvidence.fixtures";

async function setup(page: Page, options: {failed?: "home" | "month-summary"; mixed?: boolean; mismatch?: boolean; long?: boolean} = {}) {
  const user = {id: "month-ui-user", email: "month-ui@example.com", aud: "authenticated", role: "authenticated"};
  const org = {id: "month-ui-org", name: "月份測試組織", kind: "personal", role: "owner", timezone: "Asia/Taipei", today: "2026-09-23"};
  let failed = options.failed;
  const writes: string[] = [];
  await page.clock.setFixedTime(new Date("2026-09-23T02:00:00Z"));
  await page.route("**/auth/v1/**", route => route.fulfill({json: {access_token: "local-ui-fixture-token", refresh_token: "local-ui-fixture-refresh", token_type: "bearer", expires_in: 3600, expires_at: Math.floor(Date.now()/1000)+3600, user}}));
  await page.route("**/api/**", async route => {
    const url = new URL(route.request().url()), key = url.pathname;
    if (route.request().method() !== "GET") { writes.push(key); return route.fulfill({status: 503, json: {detail: "Fixture: writes unavailable"}}); }
    const month = url.searchParams.get("month") ?? MONTH;
    const data = monthEvidence(month);
    if (options.long) { const name = "VeryLongCampaignNameWithoutAnySpaces".repeat(5); data.summary.suggestions = [{key: "cleanup:cmp_month", kind: "cleanup", campaign_id: "cmp_month", campaign_name: name, objective: "購買", campaign_objective: "sales", title: "改善成本後再安排下一期", why: name, action_url: "/brands/brd_month_ui/ads/campaigns/cmp_month/propose/cleanup/cmp_month"}]; }
    if (options.mixed) data.summary.orders!.this_evidence.order_summary.reported_currencies = ["TWD", "USD"];
    if (options.mismatch) {data.home.currency = "USD"; data.home.pace!.budget_comparison = {reason: "currency_mismatch"};}
    if (failed && key.endsWith("/"+failed)) {failed = undefined; return route.fulfill({status: 502, json: {detail: "fixture read failed"}});}
    const bodies: Record<string, unknown> = {
      "/api/identity/me": {user, org, orgs: [org]},
      "/api/dashboard/overview": {data: [{brand_id: MONTH_BRAND, brand_name: "月份付款證據品牌", health: "yellow", revenue_this_month: null, revenue_mom_pct: null, next_step: null}]},
      "/api/jobs/active": {data: [], total: 0, other_count: 0, done_today: 0, failed_today: 0, worker_alive: null, stalled: false, worker_health: {state: "unknown", checked_at: null, last_heartbeat_at: null, reason_code: "test_queue"}},
      [`/api/ads/brands/${MONTH_BRAND}/rules`]: MONTH_RULES,
      [`/api/ads/brands/${MONTH_BRAND}/month-summary`]: data.summary,
      [`/api/ads/brands/${MONTH_BRAND}/home`]: data.home,
      [`/api/ads/brands/${MONTH_BRAND}/settle`]: data.settle,
      "/api/figures": {bases: {}}, "/api/interrupts": {data: [], total: 0},
    };
    return route.fulfill(key in bodies ? {json: bodies[key]} : {status: 503, json: {detail: "Fixture: optional read unavailable"}});
  });
  await page.goto("/app/login");
  await page.getByLabel("Email").fill(user.email); await page.getByLabel("密碼").fill("local-ui-fixture-password");
  await page.getByRole("button", {name: "登入", exact: true}).click();
  await page.waitForURL(url => !url.pathname.includes("/login"));
  await page.goto(`/app/brands/${MONTH_BRAND}/ads/month`);
  return writes;
}
async function capture(page: Page, name: string) {
  const out = process.env.F54_I10_EVIDENCE_DIR;
  if (!out) return;
  await mkdir(out, {recursive: true});
  await page.evaluate(() => window.scrollTo(0,0));
  await page.screenshot({path: path.join(out, `${name}-${page.viewportSize()!.width}.png`), fullPage: true});
}

test("paid subtotal never includes pending orders or mirror income; refund states open by keyboard", async ({page}) => {
  const writes = await setup(page);
  const orders = page.getByRole("region", {name: "已收集的已付款訂單淨額"});
  await expect(orders.getByText("1,200（幣別未核實）", {exact: true})).toBeVisible();
  await expect(orders.getByText("5 筆已付款・2 筆金額已知・2 筆已退款", {exact: true})).toBeVisible();
  await expect(orders.getByText(/9,999/)).toHaveCount(0);
  const fold = orders.getByRole("button", {name: "訂單來源與狀態"});
  await expect(fold).toHaveAttribute("aria-expanded", "false");
  for (const width of [1024,1920]) { await page.setViewportSize({width, height: 1080}); await capture(page, "built-month"); }
  await fold.focus(); await page.keyboard.press("Enter"); await expect(fold).toBeFocused();
  await expect(orders.getByText("4 筆待付款・3 筆付款狀態未知").first()).toBeVisible();
  await expect(orders.getByText("3 筆金額未知・1 筆取消或作廢").first()).toBeVisible();
  for (const width of [1024,1920]) {await page.setViewportSize({width, height: 1080}); await capture(page, "built-order-details");}
  expect(writes).toEqual([]);
});
for (const failed of ["home", "month-summary"] as const) test(`${failed} failure is independent and retry restores only its block`, async ({page}) => {
  await setup(page, {failed});
  await expect(page.getByText(failed === "home" ? /每週花費讀不到/ : /這個月的分級與建議讀不到/)).toBeVisible();
  await expect(page.getByRole("region", {name: failed === "home" ? "已收集的已付款訂單淨額" : "每週花費 vs 預算步調"})).toBeVisible();
  await capture(page, `built-failed-${failed}`);
  await page.getByRole("button", {name: "重試", exact: true}).click();
  await expect(page.getByText("已花 3,500 TWD", {exact: true})).toBeVisible();
  await expect(page.getByText("1,200（幣別未核實）", {exact: true})).toBeVisible();
});
test("mixed order currencies and incompatible pacing never form a common money chart", async ({page}) => {
  await setup(page, {mixed: true, mismatch: true});
  await expect(page.getByText("多幣別，無法合計", {exact: true})).toBeVisible();
  const weekly = page.getByRole("region", {name: "每週花費 vs 預算步調"});
  await expect(weekly.getByText("已設月預算 60,000 TWD", {exact: true})).toBeVisible();
  await expect(weekly.locator("[data-week]")).toHaveCount(0);
  for (const width of [1024,1920]) {await page.setViewportSize({width, height: 1080}); await capture(page, "built-mixed");}
});
test("completed imported source follows its exact canonical settle and preserves cost/cap numbers", async ({page}) => {
  const writes = await setup(page);
  await page.getByRole("button", {name: "8 月", exact: true}).click();
  await expect(page).toHaveURL(new RegExp(`month=${PREVIOUS}`));
  const next = page.getByRole("link", {name: "回顧本期，準備下一期 →"});
  await expect(next).toHaveAttribute("href", `/app/brands/${MONTH_BRAND}/ads/settle/${PREVIOUS}?step=result`);
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", {name: "下載 CSV", exact: true}).click();
  const csv = await readFile((await (await downloadPromise).path())!, "utf8");
  expect(csv).toContain("3500,7,500,100,太貴,TWD,TWD");
  await capture(page, "built-completed"); await next.click();
  await expect(page).toHaveURL(new RegExp(`settle/${PREVIOUS}\\?step=result`));
  await expect(page.getByText("3,500 TWD", {exact: true}).first()).toBeVisible();
  await expect(page.getByText(/每筆 500 TWD/).first()).toBeVisible();
  await expect(page.getByText(/上限 100 TWD/).first()).toBeVisible();
  await page.getByRole("link", {name: /投放中心/}).last().click();
  await expect(page).toHaveURL(new RegExp(`/brands/${MONTH_BRAND}/ads$`));
  expect(writes).toEqual([]);
});

test("long source names and proposal explanations fit at desktop widths without hiding controls", async ({page}) => {
  await setup(page, {long: true});
  for (const width of [1024,1920]) {
    await page.setViewportSize({width, height: 1080});
    const card = page.getByRole("region", {name: "改善成本後再安排下一期"});
    await expect(card.getByRole("link", {name: "看提議（核准或拒絕）→"})).toBeVisible();
    expect(await page.locator("#root").evaluate(node => node.scrollWidth-node.clientWidth)).toBeLessThanOrEqual(1);
    expect(await card.evaluate(node => node.scrollWidth-node.clientWidth)).toBeLessThanOrEqual(1);
  }
});
