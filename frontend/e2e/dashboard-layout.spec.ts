import { expect, test } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";

test("自訂看板可儲存、鍵盤排序，並與其他品牌隔離", async ({ page }) => {
  const stamp = Date.now();
  await page.goto("/app/login");
  await page.getByRole("button", { name: "還沒有帳號？註冊新帳號" }).click();
  await page.getByLabel("Email").fill(`layout-${stamp}@example.com`);
  await page.getByLabel("密碼").fill(`layout-password-${stamp}`);
  await page.getByRole("button", { name: "註冊", exact: true }).click();
  await page.getByRole("link", { name: "新增品牌" }).first().click();
  await page.getByLabel("品牌名稱", { exact: true }).fill(`版面測試 A ${stamp}`);
  // F05-I06：投放史二選一做在步驟一表單裡，沒選不能往下。
  await page.getByRole("radio", { name: "完全沒投過" }).check();
  await page.getByRole("button", { name: "下一步 →" }).click();
  // 沒東西可掃，草稿直接停在精靈第 3 步；回品牌頁才看得到經營概況。
  await page.waitForURL(/\/app\/brands\/brd_.+\/intake/);
  const firstBrandId = new URL(page.url()).pathname.split("/")[3];
  await page.goto(`/app/brands/${firstBrandId}`);
  await expect(
    page.getByRole("heading", { name: "經營概況", exact: true }),
  ).toBeVisible();
  const firstBrandUrl = page.url();
  await page.getByRole("button", { name: "新增檢視", exact: true }).click();
  const panel = page.getByRole("dialog", { name: "自訂看板版面" });
  await expect(panel).toBeVisible();
  await panel.getByLabel("檢視名稱", { exact: true }).fill("每週廣告檢查");
  await panel.getByLabel("曝光次數", { exact: true }).uncheck();
  await panel
    .getByRole("button", { name: "活動概況上移", exact: true })
    .focus();
  await page.keyboard.press("Enter");
  await panel.getByLabel("活動概況寬度").selectOption("full");
  await page.keyboard.press("Escape");
  await expect(panel).not.toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("button", { name: "每週廣告檢查", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".dashboard-metrics article")).toHaveCount(4);
  await expect(page.locator(".dashboard-widget").nth(1)).toHaveAttribute(
    "aria-label",
    "活動概況",
  );
  await expect(
    page.getByRole("region", { name: "活動概況", exact: true }),
  ).toHaveAttribute("data-width", "full");

  // Browser-only preferences must not leak to a newly created brand in the same organization.
  await page.goto("/app/intake/new");
  await page.getByLabel("品牌名稱", { exact: true }).fill(`版面測試 B ${stamp}`);
  await page.getByRole("radio", { name: "完全沒投過" }).check();
  await page.getByRole("button", { name: "下一步 →" }).click();
  await page.waitForURL(/\/app\/brands\/brd_.+\/intake/);
  const secondBrandId = new URL(page.url()).pathname.split("/")[3];
  await page.goto(`/app/brands/${secondBrandId}`);
  await expect(
    page.getByRole("heading", { name: "經營概況", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "每週廣告檢查", exact: true }),
  ).toHaveCount(0);
  await expect(page.locator(".dashboard-metrics article")).toHaveCount(5);
  await page.getByRole("button", { name: "切換品牌", exact: true }).click();
  await page
    .getByRole("menuitem", { name: `版面測試 A ${stamp}`, exact: true })
    .click();
  await expect(page).toHaveURL(firstBrandUrl);
  await expect(
    page.getByRole("button", { name: "每週廣告檢查", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "自訂版面", exact: true }).click();
  await panel.getByRole("button", { name: "刪除此檢視", exact: true }).click();
  await expect(page.locator(".dashboard-metrics article")).toHaveCount(5);
});

test("last home block exposes its reason by keyboard and survives reload/reset", async ({ page }) => {
  // This UI-only fixture never writes an account, brand or platform object.
  const user = { id: "layout-ui-user", email: "layout-ui@example.com", aud: "authenticated", role: "authenticated" };
  const org = { id: "layout-ui-org", name: "版面驗證組織", kind: "personal", role: "owner", timezone: "Asia/Taipei", today: "2026-10-06" };
  const brandId = "layout-ui-brand";
  const key = `brand-os:dashboard:${JSON.stringify([user.id, org.id, brandId])}`;
  await page.route("**/auth/v1/**", async (route) => {
    await route.fulfill({ json: {
      access_token: "local-ui-fixture-token", refresh_token: "local-ui-fixture-refresh",
      token_type: "bearer", expires_in: 3600, expires_at: Math.floor(Date.now() / 1000) + 3600, user,
    } });
  });
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const bodies: Record<string, unknown> = {
      "/api/identity/me": { user, org, orgs: [org] },
      "/api/dashboard/overview": { data: [{ brand_id: brandId, brand_name: "Beast Prime 控制項驗證品牌與長名稱", health: "green", revenue_this_month: null, revenue_mom_pct: null, next_step: null }] },
      [`/api/meta/brands/${brandId}/spend`]: { campaigns: [], totals: [], last_pull_at: null, data_pulled_at: null, attribution_label: null },
      [`/api/intake/brands/${brandId}/products`]: { data: { products: [], bundles: [], suggestions: [] } },
      [`/api/dashboard/brands/${brandId}/month`]: { data: { spend_by_currency: [], currency: "TWD", revenue: 4820, margin: 3120, margin_unknown_sku_count: 0, roas_all_channels: null, roas_unknown: null, has_orders: true, marketplace_uncalibrated: false } },
      "/api/jobs/active": { data: [], total: 0, other_count: 0, done_today: 0, failed_today: 0, generated_at: "2026-10-06T00:00:00Z", worker_alive: true, stalled: false },
      "/api/dashboard/archived-brands": { data: [] },
      "/api/inbox": { data: { open: [], resolved: [] } },
      "/api/figures": { bases: {} },
    };
    await route.fulfill(url.pathname in bodies
      ? { json: bodies[url.pathname] }
      : { status: 503, json: { detail: "Isolated layout fixture: optional data unavailable" } });
  });
  await page.goto("/app/login");
  await page.getByLabel("Email").fill(user.email);
  await page.getByLabel("密碼").fill("local-ui-fixture-password");
  await page.getByRole("button", { name: "登入", exact: true }).click();
  await page.waitForURL(/\/app\/?$/);
  await page.evaluate(({ key }) => localStorage.setItem(key, JSON.stringify({
    version: 1, activeId: "ads",
    views: [{ id: "ads", name: "最後一個區塊", metrics: [], widgets: [{ id: "commerce", width: "full" }] }],
  })), { key });
  await page.goto(`/app/brands/${brandId}`);
  await page.getByRole("button", { name: "自訂版面", exact: true }).click();
  const panel = page.getByRole("dialog", { name: "自訂看板版面" });
  const last = panel.getByRole("checkbox", { name: "本月營收與毛利", exact: true });
  const group = panel.getByRole("group", { name: "本月營收與毛利", exact: true });
  const reason = panel.getByText("至少保留一個區塊；先勾選其他指標或區塊，才能取消這項。", { exact: true });
  await expect(last).toBeDisabled();
  await expect(last).toBeChecked();
  await expect(reason).toBeVisible();
  await expect(last).toHaveAttribute("aria-describedby", await reason.getAttribute("id") as string);
  await expect(group).toHaveAttribute("aria-describedby", await reason.getAttribute("id") as string);
  await panel.getByRole("textbox", { name: "檢視名稱" }).focus();
  for (let i = 0; i < 10 && !(await group.evaluate((el) => document.activeElement === el)); i++) await page.keyboard.press("Tab");
  await expect(group).toBeFocused();
  await page.keyboard.press("Space");
  await expect(last).toBeChecked();
  if (process.env.F52_UI_EVIDENCE_DIR) {
    await mkdir(process.env.F52_UI_EVIDENCE_DIR, { recursive: true });
    for (const width of [1024, 1920]) {
      await page.setViewportSize({ width, height: 1080 });
      await group.focus();
      await expect(reason).toBeVisible();
      await page.screenshot({ path: path.join(process.env.F52_UI_EVIDENCE_DIR, `built-${width}.png`) });
    }
  }
  await panel.getByRole("button", { name: "完成", exact: true }).click();
  await page.reload();
  await page.getByRole("button", { name: "自訂版面", exact: true }).click();
  await expect(last).toBeDisabled();
  await expect(reason).toBeVisible();
  await panel.getByRole("checkbox", { name: "廣告花費", exact: true }).check();
  await expect(last).toBeEnabled();
  await expect(reason).toHaveCount(0);
  await last.uncheck();
  await expect(panel.getByRole("checkbox", { name: "廣告花費", exact: true })).toBeDisabled();
  await panel.getByRole("button", { name: "重設此檢視", exact: true }).click();
  await expect(panel.locator('input[type="checkbox"]:checked')).toHaveCount(9);
  await expect(panel.locator('input[type="checkbox"]:disabled')).toHaveCount(0);
  await panel.getByRole("button", { name: "完成", exact: true }).click();
  await page.reload();
  await page.getByRole("button", { name: "自訂版面", exact: true }).click();
  await expect(panel.locator('input[type="checkbox"]:checked')).toHaveCount(9);
  await expect(panel.locator('input[type="checkbox"]:disabled')).toHaveCount(0);
});
