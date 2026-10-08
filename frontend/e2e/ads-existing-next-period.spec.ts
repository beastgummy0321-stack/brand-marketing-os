import {expect, test, type Page} from "@playwright/test";
import {mkdir} from "node:fs/promises";
import path from "node:path";
import {SETTLE_BRAND, SETTLE_MONTH, settleEvidence, nextPeriodEvidence} from "../src/components/ads/settle/settleEvidence.fixtures";
import {MONTH_RULES} from "../src/components/ads/month/monthEvidence.fixtures";

async function setup(page: Page, options: {written?: boolean; failedSource?: boolean; empty?: boolean; notEnded?: boolean; long?: boolean; failedSave?: boolean} = {}) {
  const user = {id: "settle-ui-user", email: "settle-ui@example.com", aud: "authenticated", role: "authenticated"};
  const org = {id: "settle-ui-org", name: "來源接續測試", kind: "personal", role: "owner", timezone: "Asia/Taipei", today: "2026-09-23"};
  let failed = options.failedSource, failedSave = options.failedSave;
  let view = settleEvidence(options.written ? "written" : options.notEnded ? "not_ended" : "open");
  const source = nextPeriodEvidence();
  if (options.empty) {view.rows = []; view.campaigns = []; view.results = view.cost_per_result = view.spent = null; source.source_campaigns = []; source.eligible_learning_refs = [];}
  if (options.notEnded) {view.month = "2026-09"; view.start = "2026-09-01"; view.end = "2026-09-30"; view.days = 30;}
  if (options.written) view.rows[0] = {...view.rows[0], fate: "skip", grade: "insufficient", skip_reason: "目前原來源尚未核實"};
  if (options.long) {const name = "LongSourceCampaignNameWithoutSpaces".repeat(6); source.source_campaigns[1].name = name; view.campaigns[1].name = name; view.rows[1].campaign_name = name;}
  const writes: string[] = [];
  await page.clock.setFixedTime(new Date("2026-09-23T02:00:00Z"));
  await page.route("**/auth/v1/**", route => route.fulfill({json: {access_token: "local-ui-fixture-token", refresh_token: "local-ui-fixture-refresh", token_type: "bearer", expires_in: 3600, expires_at: Math.floor(Date.now()/1000)+3600, user}}));
  await page.route("**/api/**", async route => {
    const url = new URL(route.request().url()), key = url.pathname;
    if (route.request().method() !== "GET") {
      writes.push(key);
      if (key.endsWith("/settle")) {
        if (failedSave) {failedSave = false; return route.fulfill({status: 503, json: {detail: "Fixture write failed"}});}
        view = settleEvidence("written"); return route.fulfill({json: view});
      }
      return route.fulfill({status: 503, json: {detail: "Fixture: unexpected write blocked"}});
    }
    if (key.endsWith("/next-period")) {
      if (failed) {failed = false; return route.fulfill({status: 502, json: {detail: "Fixture source unavailable"}});}
      expect(url.searchParams.get("month")).toBe(SETTLE_MONTH); return route.fulfill({json: source});
    }
    const bodies: Record<string, unknown> = {
      "/api/identity/me": {user, org, orgs: [org]},
      "/api/dashboard/overview": {data: [{brand_id: SETTLE_BRAND, brand_name: "既有活動接續證據品牌", health: "yellow", revenue_this_month: null, revenue_mom_pct: null, next_step: null}]},
      "/api/jobs/active": {data: [], total: 0, other_count: 0, done_today: 0, failed_today: 0, worker_alive: null, stalled: false, worker_health: {state: "unknown", checked_at: null, last_heartbeat_at: null, reason_code: "test_queue"}},
      [`/api/ads/brands/${SETTLE_BRAND}/rules`]: MONTH_RULES,
      [`/api/ads/brands/${SETTLE_BRAND}/settle`]: view,
      [`/api/ads/brands/${SETTLE_BRAND}/queue`]: {items: [], counts: {}, total_ads: 2, kinds_available: [], kinds_pending: [], settle: null},
      "/api/figures": {bases: {}}, "/api/interrupts": {data: [], total: 0},
    };
    return route.fulfill(key in bodies ? {json: bodies[key]} : {status: 503, json: {detail: "Fixture: optional read unavailable"}});
  });
  await page.goto("/app/login"); await page.getByLabel("Email").fill(user.email); await page.getByLabel("密碼").fill("local-ui-fixture-password");
  await page.getByRole("button", {name: "登入", exact: true}).click(); await page.waitForURL(url => !url.pathname.includes("/login"));
  await page.goto(`/app/brands/${SETTLE_BRAND}/ads/settle/${view.month}?step=${options.written ? "note" : "result"}`);
  return writes;
}
async function capture(page: Page, name: string) {
  const out = process.env.F54_I11_EVIDENCE_DIR;
  if (!out) return;
  await mkdir(out, {recursive: true}); await page.evaluate(() => window.scrollTo(0,0));
  await page.screenshot({path: path.join(out, `${name}-${page.viewportSize()!.width}.png`), fullPage: true});
}

test("completed native sources survive keyboard selection, back and reload; navigation creates nothing", async ({page}) => {
  const writes = await setup(page);
  await expect(page.getByRole("heading", {name: "這期成績", exact: true})).toBeVisible();
  const bad = page.getByRole("region", {name: "舊平台活動・相對最好仍超標"});
  await expect(bad.getByText("記成無效", {exact: true})).toBeVisible(); await expect(bad.getByText("每筆 500 TWD", {exact: true})).toBeVisible();
  const fold = page.getByRole("button", {name: "從這期來源規劃下一期"});
  await expect(fold).toHaveAttribute("aria-expanded", "false");
  await fold.focus(); await page.keyboard.press("Enter"); await expect(fold).toBeFocused();
  const pick = page.getByRole("checkbox", {name: /舊平台活動/}); await pick.focus(); await page.keyboard.press("Space");
  await expect(pick).toBeChecked(); await expect(page.getByText(/可沿用參考 0 筆/)).toBeVisible();
  await expect(page.getByRole("link", {name: "用選定來源規劃下一期 →"})).toHaveAttribute("href", `/app/brands/${SETTLE_BRAND}/ads/new?source_month=2026-08&source_campaign=native&source_revision=source-revision-1`);
  await page.getByRole("link", {name: "下一步：確認主打什麼 →"}).click();
  await expect(page).toHaveURL(/step=angle.*source_campaign=native/);
  await page.getByRole("link", {name: "← 這期成績"}).click(); await page.reload();
  await page.getByRole("button", {name: "從這期來源規劃下一期"}).click(); await expect(pick).toBeChecked();
  await page.getByRole("button", {name: "查看來源資格與排除原因"}).click(); await expect(page.getByText(/成本超過上限，不能當作成功沿用/)).toBeVisible();
  await capture(page, "built-selected-source"); expect(writes).toEqual([]);
});
test("source failure retries independently without a draft or close operation", async ({page}) => {
  const writes = await setup(page, {failedSource: true}); await page.getByRole("button", {name: "從這期來源規劃下一期"}).click();
  await expect(page.getByText(/下一期來源讀不到/)).toBeVisible(); await expect(page.getByRole("region", {name: "這期數字"})).toBeVisible();
  await capture(page, "built-source-failed"); await page.getByRole("button", {name: "重試", exact: true}).click();
  await expect(page.getByRole("checkbox", {name: /日常推廣/})).toBeVisible(); expect(writes).toEqual([]);
});
test("written legacy unknown and currently unavailable rows stay visible", async ({page}) => {
  const writes = await setup(page, {written: true}); await expect(page.getByText("已寫 3 條：留存分類有效 1、無效 1、未核實 1")).toBeVisible();
  await expect(page.getByText("「通勤帶著走」・目前待核實")).toBeVisible(); await expect(page.getByText(/另有 1 條已寫紀錄/)).toBeVisible();
  await capture(page, "built-written"); expect(writes).toEqual([]);
});
test("not-ended and empty source keep explicit blocked states", async ({page}) => {
  const writes = await setup(page, {notEnded: true}); await expect(page.getByText("這個月還沒結束", {exact: true})).toBeVisible();
  await expect(page.getByRole("button", {name: "從這期來源規劃下一期"})).toHaveCount(0); await capture(page, "built-not-ended"); expect(writes).toEqual([]);
});
test("empty completed source cannot fallback to a generic draft", async ({page}) => {
  const writes = await setup(page, {empty: true}); await page.getByRole("button", {name: "從這期來源規劃下一期"}).click();
  await expect(page.getByText("這個完成期沒有可選的活動來源。")).toBeVisible(); await expect(page.getByRole("link", {name: "用選定來源規劃下一期 →"})).toHaveCount(0);
  await capture(page, "built-empty"); expect(writes).toEqual([]);
});
test("manual angle confirmation is the only write; failed save preserves selections for retry", async ({page}) => {
  const writes = await setup(page, {failedSave: true}); await page.getByRole("link", {name: "下一步：確認主打什麼 →"}).click();
  await page.getByRole("group", {name: "通勤喝咖啡主打什麼"}).getByRole("button", {name: "保溫到公司", exact: true}).click();
  await page.getByRole("link", {name: "都對，下一步 →"}).click(); await expect(page.getByText("「保溫到公司」・本期成本達標")).toBeVisible();
  const write = page.getByRole("button", {name: "寫進筆記本（2 條）→"}); await write.click(); await expect(page.getByText("還沒寫進筆記本", {exact: true})).toBeVisible();
  await expect(page.getByText("「保溫到公司」・本期成本達標")).toBeVisible(); await capture(page, "built-save-failed"); await write.click();
  await expect(page.getByText(/已寫 3 條/)).toBeVisible(); expect(writes).toEqual([`/api/ads/brands/${SETTLE_BRAND}/settle`, `/api/ads/brands/${SETTLE_BRAND}/settle`]);
});
