import { expect, test, type Page } from "@playwright/test";
import { readFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

const contextPath = process.env.F15_B_E2E_CONTEXT;
test.skip(!contextPath, "Requires phase B isolated fixture server; never use real platform accounts.");
interface Fixture { base_url: string; schema: string; brand_id: string; browser_review_id: string; evidence_dir: string }
async function capture(page: Page, directory: string, state: string) {
  for (const width of [1024, 1920]) {
    await page.setViewportSize({ width, height: 1080 });
    await page.evaluate(() => window.scrollTo(0, 0));
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 2)).toBe(true);
    await page.screenshot({ path: join(directory, `${state}-${width}.png`), fullPage: true });
  }
}

test("B: normal entry, commerce evidence, editable copy handoff and next review", async ({ page }) => {
  test.setTimeout(180_000);
  if (!contextPath) throw new Error("Missing isolated fixture context");
  const fixture = JSON.parse(readFileSync(contextPath, "utf8")) as Fixture;
  expect(fixture.schema).toMatch(/^f13_runtime_[a-f0-9]+$/);
  expect(new URL(fixture.base_url).hostname).toMatch(/^(localhost|127\.0\.0\.1)$/);
  expect(process.env.E2E_BASE_URL).toBe(fixture.base_url);
  const directory = join(fixture.evidence_dir, "ui-B"); mkdirSync(directory, { recursive: true });
  const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
  await page.goto("/app/");
  await page.getByLabel("Email").fill("123@example.com");
  await page.getByLabel("密碼").fill("123456");
  await page.getByRole("button", { name: "登入", exact: true }).click();
  await page.getByRole("link", { name: "F13 隔離驗收品牌", exact: true }).click();
  await page.getByRole("link", { name: "投放中心", exact: true }).click();
  await page.getByTestId("campaign-grid").getByText("F13 測試｜暫停活動", { exact: true }).first().click();
  const reviewsResponse = page.waitForResponse(response => response.url().endsWith("/reviews") && response.request().method() === "GET");
  await page.getByRole("button", { name: "成效", exact: true }).click();
  const reviews = (await (await reviewsResponse).json()).reviews as { id: string; window_start: string; window_end: string }[];
  const first = reviews.find(review => review.id === fixture.browser_review_id);
  expect(first).toBeTruthy();
  await expect(page.getByRole("region", { name: "商城與通路證據" })).toBeVisible();
  await capture(page, directory, "second-evidence");
  await page.getByRole("button", { name: "其他檢討與歷史紀錄", exact: true }).click();
  await page.getByRole("button", { name: new RegExp(`${first!.window_start} — ${first!.window_end}`) }).click();
  await page.getByRole("link", { name: "只改文案，保留圖片", exact: true }).click();
  await expect(page.getByLabel("變更 1 新內文", { exact: true })).toHaveValue("了解更多");
  await page.getByLabel("清單名稱", { exact: true }).fill(`瀏覽器承接判讀 ${Date.now()}`);
  await page.getByLabel("變更 1 新內文", { exact: true }).fill("了解更多");
  await capture(page, directory, "copy-editor");
  const saveResponse = page.waitForResponse(response => response.url().endsWith("/change-sets") && response.request().method() === "POST");
  await page.getByRole("button", { name: "保存清單，檢視並核准", exact: true }).click();
  const save = await saveResponse;
  expect(save.ok()).toBe(true);
  expect(save.request().postDataJSON().review_id).toBe(fixture.browser_review_id);
  await expect(page.getByRole("button", { name: "核准這份變更清單", exact: true })).toBeVisible();
  await page.reload();
  await capture(page, directory, "approval-reopened");
  await page.getByRole("button", { name: "核准這份變更清單", exact: true }).click();
  await page.getByRole("button", { name: "我已手動完成這一項", exact: true }).click();
  await expect(page.getByText("已自行回報，待核對", { exact: true })).toBeVisible();
  expect((await page.request.post("/__f13/state", { data: { creative_revision: 4 } })).ok()).toBe(true);
  await page.getByRole("button", { name: "讀回核對這一項", exact: true }).click();
  await expect(page.getByText("設定已讀回", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText("設定已讀回", { exact: true })).toBeVisible();
  await capture(page, directory, "copy-readback");
  await page.getByRole("button", { name: "成效", exact: true }).click();
  await page.getByRole("button", { name: "其他檢討與歷史紀錄", exact: true }).click();
  await page.getByRole("button", { name: new RegExp(`${first!.window_start} — ${first!.window_end}`) }).click();
  await page.getByRole("button", { name: "準備下一次檢討", exact: true }).click();
  await expect(page.getByText(/承接上一輪判讀與操作紀錄/)).toBeVisible();
  await page.getByRole("button", { name: "開始本次檢討", exact: true }).click();
  await expect(page.getByText("建議已備妥", { exact: true })).toBeVisible();
  await expect(page.getByText("先觀察，再決定", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "查看完整判讀依據、缺漏與上一輪結果", exact: true }).click();
  await expect(page.getByText(/已帶入.*項操作核對紀錄/)).toBeVisible();
  await capture(page, directory, "next-review");
  await page.getByRole("button", { name: "記錄無法判定", exact: true }).click();
  await page.getByLabel("原因與後續處理", { exact: true }).fill("商城報表涵蓋範圍未確認；補齊訂單、退款與日期口徑後再重看，不據此加碼。");
  await page.getByRole("button", { name: "保存檢討決定", exact: true }).click();
  await page.reload();
  await expect(page.getByText("本次無法判定", { exact: true })).toBeVisible();
  await capture(page, directory, "unjudgeable-reopened");
  expect(errors).toEqual([]);
});
