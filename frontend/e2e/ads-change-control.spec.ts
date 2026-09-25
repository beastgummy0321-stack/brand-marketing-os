import { expect, test, type Page } from "@playwright/test";
import { readFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

const contextPath = process.env.F15_E2E_CONTEXT;
test.skip(!contextPath, "Requires dedicated F15 fixture database and held isolated server.");
interface Context { base_url: string; schema: string; org_id: string; brand_id: string; second_brand_id: string; imported_campaign_id: string; evidence_dir: string }
async function screenshot(page: Page, directory: string, state: string) {
  for (const width of [1024, 1920]) {
    await page.setViewportSize({ width, height: 1080 });
    await page.evaluate(() => window.scrollTo(0, 0));
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 2)).toBe(true);
    await page.screenshot({ path: join(directory, `${state}-${width}.png`), fullPage: true });
  }
}
test("A: normal entry, save/reopen/approve, lost response replay and independent readback", async ({ page }) => {
  test.setTimeout(180_000);
  if (!contextPath) throw new Error("Missing isolated fixture context");
  const fixture = JSON.parse(readFileSync(contextPath, "utf8")) as Context;
  expect(fixture.schema).toMatch(/^f13_runtime_[a-f0-9]+$/);
  expect(new URL(fixture.base_url).hostname).toMatch(/^(localhost|127\.0\.0\.1)$/);
  expect(process.env.E2E_BASE_URL).toBe(fixture.base_url);
  const evidence = join(fixture.evidence_dir, "ui-A"); mkdirSync(evidence, { recursive: true });
  const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
  await page.goto("/app/");
  await page.getByLabel("Email").fill("123@example.com");
  await page.getByLabel("密碼").fill("123456");
  await page.getByRole("button", { name: "登入", exact: true }).click();
  await expect(page).not.toHaveURL(/\/login/);
  const brandLink = page.getByRole("link", { name: "F13 隔離驗收品牌", exact: true });
  await expect(brandLink).toBeVisible();
  await brandLink.click();
  await page.getByRole("link", { name: "投放中心", exact: true }).click();
  // F28-I08 起首頁是 v9 board D：h1「N 月的廣告」，月預算編輯要先按預算進度卡的
  // 「調整」才會展開既有 `MonthlyBudgetPanel`。
  await expect(page.getByRole("heading", { level: 1, name: /^\d{1,2} 月的廣告$/ })).toBeVisible();
  await screenshot(page, evidence, "home");
  await page.getByRole("button", { name: "調整", exact: true }).click();
  await expect(page.getByRole("heading", { name: "本月廣告預算", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "調整月總額", exact: true }).click();
  await page.getByLabel("每月品牌總額", { exact: true }).fill("60000");
  await page.getByRole("button", { name: "確認月總額", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "月總額已保存" })).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "調整", exact: true }).click();
  await expect(page.getByText("TWD 60,000", { exact: true })).toBeVisible();
  // Normal campaign card entry followed by the workspace tab, not a fabricated internal state.
  await page.getByTestId("campaign-grid").getByText("F13 測試｜暫停活動", { exact: true }).first().click();
  await page.getByRole("button", { name: "變更與核對", exact: true }).click();
  // F30-I09 (v10): the tab is the 變更紀錄 timeline; the change list lives in the fold 「進階：自己建一份變更」.
  await expect(page.getByRole("heading", { name: "變更紀錄", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "進階：自己建一份變更", exact: true }).click();
  await page.getByRole("button", { name: "建立變更清單", exact: true }).first().click();
  await page.getByLabel("清單名稱", { exact: true }).fill(`瀏覽器文案核准 ${Date.now()}`);
  await page.getByLabel("變更 1 新內文", { exact: true }).fill("先了解適合自己的補給方式，再選擇日常所需。");
  await page.getByLabel("變更 1 原因", { exact: true }).fill("隔離驗收：保留圖片，只測試新文案訴求。");
  let swallowed = false;
  const createdIds: string[] = [];
  await page.route("**/change-sets", async route => {
    if (route.request().method() !== "POST") return route.continue();
    const response = await route.fetch();
    if (response.ok()) createdIds.push((await response.json()).change_set.id);
    if (!swallowed) { swallowed = true; return route.abort("failed"); }
    return route.fulfill({ response });
  });
  await page.getByRole("button", { name: "保存清單，檢視並核准", exact: true }).click();
  await expect(page.getByRole("button", { name: "重試同一份清單", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "重試同一份清單", exact: true }).click();
  await expect(page.getByRole("button", { name: "核准這份變更清單", exact: true })).toBeVisible();
  expect(createdIds).toHaveLength(2); expect(createdIds[1]).toBe(createdIds[0]);
  await page.unroute("**/change-sets");
  await screenshot(page, evidence, "approval");
  await page.reload();
  await page.getByRole("button", { name: "核准這份變更清單", exact: true }).click();
  await page.getByRole("button", { name: "我已手動完成這一項", exact: true }).click();
  await expect(page.getByText("已自行回報，待核對", { exact: true })).toBeVisible();
  await expect(page.getByText("設定已讀回", { exact: true })).toHaveCount(0);
  // Only a local fixture flag changes; no platform operation or credentials are involved.
  expect((await page.request.post("/__f13/state", { data: { fail_next: true } })).ok()).toBe(true);
  await page.getByRole("button", { name: "讀回核對這一項", exact: true }).click();
  await expect(page.getByText("結果未知，待補核對", { exact: true })).toBeVisible();
  await screenshot(page, evidence, "unknown");
  expect((await page.request.post("/__f13/state", { data: { fail_next: false, creative_revision: 2 } })).ok()).toBe(true);
  await page.getByRole("button", { name: "讀回核對這一項", exact: true }).click();
  await expect(page.getByText("設定已讀回", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText("設定已讀回", { exact: true })).toBeVisible();
  await screenshot(page, evidence, "readback");
  expect((await page.request.post("/__f13/state", { data: { creative_revision: 3 } })).ok()).toBe(true);
  await page.getByRole("button", { name: "重新核對這一項", exact: true }).click();
  await expect(page.getByText("與核准內容不同", { exact: true })).toBeVisible();
  await screenshot(page, evidence, "deviated");
  const previousUrl = page.url();
  await page.getByRole("button", { name: "依目前設定另建清單", exact: true }).click();
  await expect(page.getByText("平台外部另改的文案", { exact: true })).toBeVisible();
  await page.getByLabel("清單名稱", { exact: true }).fill("以平台新版為基準重新檢視");
  await page.getByRole("button", { name: "保存清單，檢視並核准", exact: true }).click();
  await expect(page).not.toHaveURL(previousUrl);
  await page.getByRole("button", { name: "暫緩", exact: true }).click();
  await page.getByLabel("決定原因", { exact: true }).fill("等待商城營收補齊後再判斷。");
  const revisit = new Date(); revisit.setDate(revisit.getDate() + 1);
  await page.getByLabel("重看時間", { exact: true }).fill(`${revisit.getFullYear()}-${String(revisit.getMonth() + 1).padStart(2, "0")}-${String(revisit.getDate()).padStart(2, "0")}T09:00`);
  await page.getByRole("button", { name: "保存決定", exact: true }).click();
  await expect(page.getByText("已暫緩", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "以平台新版為基準重新檢視", exact: true })).toBeVisible();
  await expect(page.getByText("已暫緩", { exact: true })).toBeVisible();
  await expect(page.getByText("等待商城營收補齊後再判斷。", { exact: true })).toBeVisible();
  await screenshot(page, evidence, "revised-deferred");
  expect(errors).toEqual([]);
});
