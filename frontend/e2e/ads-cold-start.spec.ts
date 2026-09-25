import { expect, test, type Page, type Response } from "@playwright/test";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const contextPath = process.env.F15_C_E2E_CONTEXT;
test.skip(!contextPath, "Requires phase C local fixture; no live model or platform accounts.");

interface Fixture {
  base_url: string;
  schema: string;
  brand_id: string;
  phase: string;
  evidence_dir: string;
  cold_campaign_id: string;
}
interface PlannedAd { id: string; name: string; placement_id: string | null; placement_revision: number | null; assignment_status: string }
interface Assigned { planned_ads: PlannedAd[]; ready_placements: { id: string; revision: number; filename: string }[] }

function responseFor(page: Page, suffix: string, method = "POST") {
  return page.waitForResponse(response => new URL(response.url()).pathname.endsWith(suffix) && response.request().method() === method);
}
async function successful(pending: Promise<Response>) {
  const response = await pending;
  expect(response.ok(), await response.text()).toBe(true);
  return response;
}
async function capture(page: Page, directory: string, name: string) {
  for (const width of [1024, 1920]) {
    await page.setViewportSize({ width, height: 1080 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 2)).toBe(true);
    await page.screenshot({ path: join(directory, `${name}-${width}.png`), fullPage: true });
  }
}

test("C cold start: login, create from brand, confirm strategy, plan and assign saved media through UI", async ({ page }) => {
  test.setTimeout(240_000);
  page.setDefaultTimeout(15_000);
  if (!contextPath) throw new Error("Missing isolated phase C context");
  const fixture = JSON.parse(readFileSync(contextPath, "utf8")) as Fixture;
  expect(fixture.schema).toMatch(/^f13_runtime_[a-f0-9]+$/);
  expect(fixture.phase).toBe("C");
  expect(new URL(fixture.base_url).hostname).toMatch(/^(localhost|127\.0\.0\.1)$/);
  expect(process.env.E2E_BASE_URL).toBe(fixture.base_url);
  const directory = join(fixture.evidence_dir, "ui-cold-start");
  mkdirSync(directory, { recursive: true });
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const beforeResponse = await page.request.get("/__f13/state");
  expect(beforeResponse.ok()).toBe(true);
  const before = await beforeResponse.json();

  // API-prepared image originals are selected through the normal UI. This campaign,
  // its strategy, plan, placement edits and assignments are all created by UI actions.
  await page.goto("/app/");
  await page.getByLabel("Email").fill("123@example.com");
  await page.getByLabel("密碼").fill("123456");
  await page.getByRole("button", { name: "登入", exact: true }).click();
  await page.getByRole("link", { name: "F13 隔離驗收品牌", exact: true }).click();
  // F30-I05: the wizard picks one of the brand's products; add one through the products page (manual, no spend).
  const productName = `F13 冷啟動商品 ${Date.now()}`;
  await page.goto(`/app/brands/${fixture.brand_id}/products`);
  await page.getByRole("button", { name: "新增產品" }).first().click();
  await page.getByLabel("產品名稱").fill(productName);
  await page.getByRole("button", { name: "新增這個產品", exact: true }).click();
  await expect(page).toHaveURL(/\/products\/prd_/);
  await page.getByRole("link", { name: "投放中心", exact: true }).click();
  await page.getByRole("link", { name: "建立活動", exact: true }).click();
  await expect(page.getByRole("heading", { name: "建立活動", exact: true })).toBeVisible();
  const filename = "fixture-I2.png";
  await page.getByRole("button", { name: /^進階/ }).click();
  await page.getByRole("checkbox", { name: `選取 ${filename}`, exact: true }).check();
  await page.getByRole("radio", { name: new RegExp(productName) }).click();
  await page.getByRole("radio", { name: /^購買/ }).click();
  await page.getByLabel("這個活動最多花").fill("30000");
  const creation = responseFor(page, "/campaigns");
  const attachment = responseFor(page, "/placements");
  await page.getByRole("button", { name: "下一步：系統理解 →", exact: true }).click();
  const createdResponse = await successful(creation);
  const created = (await createdResponse.json()).campaign;
  expect(created.id).not.toBe(fixture.cold_campaign_id);
  expect(created.goal_text).toContain(productName);
  const attached = (await (await successful(attachment)).json()).placement;
  await expect(page.getByRole("heading", { name: "系統這樣理解", exact: true })).toBeVisible();
  await capture(page, directory, "brief-confirmation");

  const strategy = responseFor(page, `/campaigns/${created.id}/strategy`);
  await page.getByRole("button", { name: "產生策略 →", exact: true }).click();
  await successful(strategy);
  // F28-I09: nothing is preselected — the user fills the total in 自己填總額; a total above the campaign's budget cap
  // needs the second yes in the confirm sheet. Adopting also needs a cost-per-result cap (一個上限).
  await page.getByRole("button", { name: "自己填總額", exact: true }).click();
  await page.getByLabel("自己填這一期的總預算", { exact: true }).fill("800");
  const budget = responseFor(page, `/campaigns/${created.id}/strategy/scenario`);
  await page.getByRole("button", { name: "套用", exact: true }).click();
  const overCap = page.getByRole("alertdialog");
  if (await overCap.isVisible()) await overCap.getByRole("button", { name: "超出預算上限也要用", exact: true }).click();
  const budgetResult = (await (await successful(budget)).json()).campaign;
  expect(budgetResult.budget_planned).toBe(800);
  const capInput = page.getByLabel("每賣一筆最多花多少（上限）", { exact: true });
  if (await capInput.isVisible()) {
    await capInput.fill("300");
    const capSaved = responseFor(page, `/campaigns/${created.id}/target`, "PUT");
    await page.getByRole("button", { name: "儲存上限", exact: true }).click();
    await successful(capSaved);
  }
  const plan = responseFor(page, `/campaigns/${created.id}/plan`);
  await page.getByRole("button", { name: "照這個方式進行 →", exact: true }).click();
  const planned = (await (await successful(plan)).json()).campaign;
  expect(planned.status).toBe("ready");
  expect(planned.groups).toHaveLength(3);
  const plannedIds = planned.groups.flatMap((group: { ads: { id: string }[] }) => group.ads.map(ad => ad.id));
  expect(plannedIds).toHaveLength(3);
  await capture(page, directory, "plan-created");

  await page.getByRole("button", { name: "素材", exact: true }).click();
  // F30-I11: the placement list lives in the assets tab's 「進階」 fold.
  await page.getByRole("button", { name: "進階：素材需求、自帶素材與人工交接", exact: true }).click();
  await page.getByRole("button", { name: "素材安排與人工交接", exact: true }).click();
  const placement = page.getByRole("article").filter({ has: page.getByRole("heading", { name: `${filename} · 第`, exact: false }) });
  await expect(placement).toHaveCount(1);
  await placement.getByText("編輯原文與內部安排", { exact: true }).click();
  await placement.getByRole("textbox", { name: `${filename}安排標題`, exact: true }).fill("探索品牌");
  await placement.getByRole("textbox", { name: `${filename}安排內文`, exact: true }).fill("了解更多");
  await placement.getByRole("textbox", { name: `${filename}安排說明`, exact: true }).fill("品牌介紹");
  await placement.getByRole("textbox", { name: `${filename}用途`, exact: true }).fill("品牌介紹");
  const revised = responseFor(page, `/placements/${attached.id}`, "PATCH");
  await placement.getByRole("button", { name: "儲存為新版安排", exact: true }).click();
  await successful(revised);
  const confirmation = responseFor(page, `/placements/${attached.id}/confirm`);
  await placement.getByRole("button", { name: "只用我的文案，檢查並確認", exact: true }).click();
  const confirmed = (await (await successful(confirmation)).json()).placement;
  expect(confirmed.confirmed_at).toBeTruthy();
  const assignments = page.getByRole("region", { name: "指派首次投放素材", exact: true });
  await expect(assignments.getByRole("combobox", { name: "已確認成品版本", exact: true }).getByRole("option", { name: `${filename} · 版本 ${confirmed.revision}`, exact: true })).toHaveCount(1);
  await expect(assignments.getByRole("combobox", { name: "計畫中的廣告", exact: true })).toBeEnabled();
  for (const adId of plannedIds) {
    await assignments.getByRole("combobox", { name: "計畫中的廣告", exact: true }).selectOption(adId);
    await assignments.getByRole("combobox", { name: "已確認成品版本", exact: true }).selectOption(confirmed.id);
    const saved = responseFor(page, `/launch-materials/${adId}`, "PUT");
    await assignments.getByRole("button", { name: "保存素材指派", exact: true }).click();
    const result = await successful(saved);
    expect(result.request().postDataJSON()).toEqual({ placement_id: confirmed.id, revision: confirmed.revision });
  }
  await capture(page, directory, "assignments-saved");
  const reopened = responseFor(page, "/launch-materials", "GET");
  await page.reload();
  await page.getByRole("button", { name: "進階：素材需求、自帶素材與人工交接", exact: true }).click();
  await page.getByRole("button", { name: "素材安排與人工交接", exact: true }).click();
  const reread = (await (await successful(reopened)).json()) as Assigned;
  expect(reread.planned_ads.map(ad => ad.id).sort()).toEqual([...plannedIds].sort());
  expect(reread.planned_ads.every(ad => ad.assignment_status === "confirmed" && ad.placement_id === confirmed.id && ad.placement_revision === confirmed.revision)).toBe(true);
  await expect(assignments.getByText(`已指派確認版本 · ${filename} · 版本 ${confirmed.revision}`, { exact: true })).toHaveCount(3);
  await capture(page, directory, "assignments-reopened");
  const afterResponse = await page.request.get("/__f13/state");
  expect(afterResponse.ok()).toBe(true);
  const after = await afterResponse.json();
  expect(after.provider_calls - before.provider_calls).toBe(3);
  expect(after.blocked_external).toBe(before.blocked_external);
  expect(errors).toEqual([]);
  writeFileSync(join(directory, "ui-receipt.json"), JSON.stringify({
    campaign_id: created.id, api_fixture_campaign_id: fixture.cold_campaign_id,
    ui_submissions: ["create", "attach existing upload", "confirm brief and generate strategy", "custom budget", "adopt plan", "revise placement", "confirm original copy", "assign three planned ads"],
    planned_ad_ids: plannedIds, placement_id: confirmed.id, placement_revision: confirmed.revision,
    reopened_assignments: reread.planned_ads, provider_calls: after.provider_calls - before.provider_calls,
    fixture_preparation: "Only original image files and platform/model replacements were API prepared; this UI created a separate campaign.",
    limitation: "UI evidence ends at saved/reopened assignments; first launch/readback is separately verified by cold-start-api.json.",
    page_errors: errors,
  }, null, 2));
});
