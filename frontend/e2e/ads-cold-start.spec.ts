import { expect, test, type Page, type Response } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

/** Cold start, self-seeding (2026-09-26 ruling: runs in the normal `npm run e2e`, no context file, no `/__f13`).
 * A fresh account + brand + product (same setup as `ads-target.spec.ts`), then the user journey through the UI:
 * wizard create with an own PNG uploaded in 進階 (its preview made by the worker's task body, below) → 系統這樣理解 →
 * 產生策略 → 自己填總額 → cap → 照這個方式進行 → placement revised and confirmed → the confirmed version placed into
 * every planned ad (one per group; the scripted provider follows the roles the prompt offers) through the slot upload
 * (F41-I01: each ad gets its own placement of that original, confirmed and assigned) → reload and re-read.
 * The webServer's scripted provider answers brief／strategy／delivery plan; no live model or platform account. */

type ApiHeaders = Record<string, string>;
interface PlannedAd { id: string; placement_id: string | null; placement_revision: number | null; assignment_status: string }

// 1×1 PNG.
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=", "base64");

// The e2e backend's memory queue drops every job (playwright.config.ts), so the preview the worker would make never
// arrives and 確認 stays pending. Run the worker's own task body (`process_preview`) for this brand's assets instead —
// same code, same DB and Storage; `import app.main` loads `.env` the way the server does.
const PREVIEW_JOB = `
import sys, app.main
from app.core.db import connection
from app.ads.user_assets import process_preview
with connection() as conn:
    rows = conn.execute("SELECT org_id, id FROM ads_user_asset WHERE brand_id = %s", (sys.argv[1],)).fetchall()
for row in rows:
    process_preview(row["org_id"], sys.argv[1], row["id"])
`;
function runPreviewJob(brandId: string) {
  const repo = fileURLToPath(new URL("../..", import.meta.url));
  execFileSync("uv", ["run", "python", "-c", PREVIEW_JOB, brandId], { cwd: repo, stdio: "pipe", timeout: 120_000 });
}

async function api<T>(page: Page, headers: ApiHeaders, method: string, path: string, data?: unknown): Promise<T> {
  const response = await page.request.fetch(path, { method, headers, data });
  const text = await response.text();
  expect(response.ok(), `${method} ${path} failed: ${response.status()} ${text}`).toBeTruthy();
  return text ? (JSON.parse(text) as T) : ({} as T);
}
function responseFor(page: Page, suffix: string, method = "POST") {
  return page.waitForResponse(response => new URL(response.url()).pathname.endsWith(suffix) && response.request().method() === method);
}
async function successful(pending: Promise<Response>) {
  const response = await pending;
  expect(response.ok(), await response.text()).toBe(true);
  return response;
}

test("冷啟動：建立精靈帶自己的圖 → 策略 → 自己填總額 → 展開結構 → 確認素材安排 → 指派每則廣告 → 重新整理還在", async ({ page }) => {
  test.setTimeout(180_000);
  const stamp = Date.now();
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));

  // --- 註冊、建品牌（沿用 ads-target.spec.ts）；註冊後第一個帶身分的請求給 API 用的 headers ---------------------
  const overviewRequest = page.waitForRequest(request =>
    request.url().includes("/api/dashboard/overview") && Boolean(request.headers().authorization),
  );
  await page.goto("/app/login");
  await page.getByRole("button", { name: "還沒有帳號？註冊新帳號" }).click();
  await page.getByLabel("Email").fill(`ads-cold-${stamp}@example.com`);
  await page.getByLabel("密碼").fill(`ads-cold-pw-${stamp}`);
  await page.getByRole("button", { name: "註冊", exact: true }).click();
  await expect(page.getByRole("link", { name: "新增品牌" }).first()).toBeVisible();
  const raw = (await overviewRequest).headers();
  const headers: ApiHeaders = Object.fromEntries(
    [["authorization", raw.authorization], ["x-org-id", raw["x-org-id"]]].filter((e): e is [string, string] => Boolean(e[1])),
  );
  await page.getByRole("link", { name: "新增品牌" }).first().click();
  await page.getByLabel("品牌名稱", { exact: true }).fill(`冷啟動驗收品牌 ${stamp}`);
  await page.getByRole("radio", { name: "完全沒投過" }).check();
  await page.getByRole("button", { name: "下一步 →" }).click();
  await expect(page).toHaveURL(/\/app\/brands\/brd_.+\/intake/);
  const brandId = new URL(page.url()).pathname.split("/")[3];
  // F43-I04: only a finished sell-way is pickable — product onboarding (create → 賣法與價格 → 完成; synchronous, no spend).
  const productName = `冷啟動商品 ${stamp}`;
  const intake = `/api/intake/brands/${brandId}/products`;
  const onboarded = await api<{ data: { product_id: string } }>(page, headers, "POST", intake, { name: productName });
  await api(page, headers, "PUT", `${intake}/${onboarded.data.product_id}/onboarding/sell-ways`, {
    sell_ways: [{ name: "單品", price: 1580 }],
  });
  // F50 Contract R: a product with zero customer groups is not ready (not pickable, 完成 refused) — one group first.
  await api(page, headers, "PUT", `${intake}/${onboarded.data.product_id}/onboarding/who`, {
    groups: [{ who: "通勤上班族", pain_keys: ["effort"] }],
  });
  await api(page, headers, "POST", `${intake}/${onboarded.data.product_id}/onboarding/complete`);

  // --- 建立精靈：商品、購買、預算上限；進階裡上傳一張自己的圖（上傳後自動勾選）--------------------------------
  await page.goto(`/app/brands/${brandId}/ads/new`);
  await expect(page.getByRole("heading", { name: "建立活動", exact: true })).toBeVisible();
  const filename = `cold-${stamp}.png`;
  await page.getByRole("button", { name: "進階：一句話建立、自帶圖片／影片", exact: true }).click();
  await page.getByLabel("選擇自帶素材").setInputFiles({ name: filename, mimeType: "image/png", buffer: PNG });
  await page.getByRole("button", { name: "保存原檔與原文", exact: true }).click();
  await expect(page.getByRole("checkbox", { name: `選取 ${filename}`, exact: true })).toBeChecked();
  await expect(page.getByText("原檔已保存", { exact: true })).toBeVisible();
  runPreviewJob(brandId);
  // F43-I15: 要推什麼 lists the product as a section and its sell-way as the card (「單品 NT$1,580」).
  const shelf = page.getByRole("radiogroup", { name: "要推什麼" });
  await expect(shelf.getByText(productName, { exact: true })).toBeVisible();
  await shelf.getByRole("radio", { name: /^單品 1,580 TWD/ }).click();
  await page.getByRole("radio", { name: /^購買/ }).click();
  await page.getByLabel("這個活動最多花").fill("30000");
  const creation = responseFor(page, "/campaigns");
  const attachment = responseFor(page, "/placements");
  await page.getByRole("button", { name: "下一步：系統理解 →", exact: true }).click();
  const created = (await (await successful(creation)).json()).campaign;
  const attached = (await (await successful(attachment)).json()).placement;

  // --- 系統這樣理解 → 產生策略 ---------------------------------------------------------------------------
  await expect(page.getByRole("heading", { name: "系統這樣理解", exact: true })).toBeVisible();
  const strategy = responseFor(page, `/campaigns/${created.id}/strategy`);
  await page.getByRole("button", { name: "產生策略 →", exact: true }).click();
  await successful(strategy);

  // --- 策略分頁：自己填總額（超過預算上限就第二次同意）、設上限、照這個方式進行 -------------------------------
  await page.getByRole("button", { name: "自己填總額", exact: true }).click();
  await page.getByLabel("自己填這一期的總預算", { exact: true }).fill("800");
  const budget = responseFor(page, `/campaigns/${created.id}/strategy/scenario`);
  await page.getByRole("button", { name: "套用", exact: true }).click();
  expect((await (await successful(budget)).json()).campaign.budget_planned).toBe(800);
  const capInput = page.getByLabel("每賣一筆最多花多少（上限）", { exact: true });
  await capInput.fill("300");
  const capSaved = responseFor(page, `/campaigns/${created.id}/target`, "PUT");
  await page.getByRole("button", { name: "儲存上限", exact: true }).click();
  await successful(capSaved);
  const plan = responseFor(page, `/campaigns/${created.id}/plan`);
  await page.getByRole("button", { name: "照這個方式進行 →", exact: true }).click();
  const planned = (await (await successful(plan)).json()).campaign;
  expect(planned.status).toBe("ready");
  const plannedIds: string[] = planned.groups.flatMap((group: { ads: { id: string }[] }) => group.ads.map(ad => ad.id));
  // One ad per group; the group count follows the roles the strategy prompt offered (F33 Contract P).
  expect(planned.groups.length).toBeGreaterThan(0);
  expect(plannedIds).toHaveLength(planned.groups.length);

  // --- 素材分頁 → 進階 → 素材安排：改寫文案存新版、只用我的文案確認 ------------------------------------------
  const openPlacements = async () => {
    await page.getByRole("button", { name: "進階：素材需求、自帶素材與人工交接", exact: true }).click();
    await page.getByRole("button", { name: "素材安排與人工交接", exact: true }).click();
  };
  await page.getByRole("button", { name: "素材", exact: true }).click();
  await openPlacements();
  const placement = page.getByRole("article").filter({ has: page.getByRole("heading", { name: `${filename} · 第` }) });
  await expect(placement).toHaveCount(1);
  // F36-I03: an unconfirmed card's editor is open by default; only click the summary when it is still closed.
  const fold = placement.locator("details").first();
  if (!(await fold.evaluate((d) => (d as HTMLDetailsElement).open))) await placement.getByText("編輯原文與內部安排", { exact: true }).click();
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

  // --- 指派：確認版本逐一指派給每一則計畫中的廣告 ---------------------------------------------------------------
  const assignments = page.getByRole("region", { name: "指派首次投放素材", exact: true });
  const adSelect = assignments.getByRole("combobox", { name: "計畫中的廣告", exact: true });
  const versionSelect = assignments.getByRole("combobox", { name: "已確認成品版本", exact: true });
  await expect(versionSelect.getByRole("option", { name: `${filename} · 版本 ${confirmed.revision}`, exact: true })).toHaveCount(1);
  const placedByAd = new Map<string, { id: string; revision: number }>();
  for (const adId of plannedIds) {
    await adSelect.selectOption(adId);
    await versionSelect.selectOption(confirmed.id);
    const saved = responseFor(page, `/slots/${adId}/upload`, "POST");
    await assignments.getByRole("button", { name: "保存素材指派", exact: true }).click();
    const result = await successful(saved);
    expect(result.request().postDataJSON()).toEqual({ placement_id: confirmed.id });
    const placed = (await result.json()).placement;
    // No workbench copy was selected (the memory queue made none), so the confirmed version's own copy rides in.
    expect(placed.ad_id).toBe(adId);
    expect(placed.confirmed_at).toBeTruthy();
    placedByAd.set(adId, { id: placed.id, revision: placed.revision });
  }

  // --- 重新整理：指派從伺服器讀回來還在 --------------------------------------------------------------------
  const reopened = responseFor(page, "/launch-materials", "GET");
  await page.reload();
  await openPlacements();
  const reread = (await (await successful(reopened)).json()) as { planned_ads: PlannedAd[] };
  expect(reread.planned_ads.map(ad => ad.id).sort()).toEqual([...plannedIds].sort());
  expect(reread.planned_ads.every(ad =>
    ad.assignment_status === "confirmed" && ad.placement_id === placedByAd.get(ad.id)?.id && ad.placement_revision === placedByAd.get(ad.id)?.revision,
  )).toBe(true);
  for (const revision of new Set([...placedByAd.values()].map(p => p.revision))) {
    const count = [...placedByAd.values()].filter(p => p.revision === revision).length;
    await expect(assignments.getByText(`已指派確認版本 · ${filename} · 版本 ${revision}`, { exact: true })).toHaveCount(count);
  }
  expect(errors).toEqual([]);
});
