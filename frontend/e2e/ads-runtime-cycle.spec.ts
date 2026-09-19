import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import type { ReviewRound, ReviewsData } from "../src/lib/adsReviewApi";
import type { RuntimeData } from "../src/lib/adsRuntimeApi";

const contextPath = process.env.F15_D_E2E_CONTEXT;
test.skip(!contextPath, "Requires D isolated PostgreSQL worker fixture; no live model/platform.");
interface Fixture {
  phase: string; schema: string; base_url: string; evidence_dir: string;
  imported_campaign_id: string; brand_id: string; b2_entity_id: string;
  b2_review_id: string; unknown_review_id: string; first_review_id: string;
}

async function capture(page: Page, directory: string, label: string) {
  for (const width of [1920, 1024]) {
    await page.setViewportSize({ width, height: 1080 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 2)).toBe(true);
    await page.screenshot({ path: join(directory, `${label}-${width}.png`), fullPage: true });
  }
}

async function chooseHistory(page: Page, review: ReviewRound, label: string) {
  const history = page.getByRole("button", { name: "其他檢討與歷史紀錄", exact: true });
  if (await history.getAttribute("aria-expanded") !== "true") await history.click();
  const name = `${review.evidence_json.target.name} · ${review.window_start} — ${review.window_end}`;
  await page.getByRole("button").filter({ hasText: name }).filter({ hasText: label }).first().click();
  await expect.poll(() => new URL(page.url()).searchParams.get("review")).toBe(review.id);
}

test("D: normal entry, unknown recovery, saved monitoring preferences and unchanged waiting", async ({ page }) => {
  test.setTimeout(180_000);
  page.setDefaultTimeout(15_000);
  if (!contextPath) throw new Error("Missing D fixture");
  const fixture = JSON.parse(readFileSync(contextPath, "utf8")) as Fixture;
  expect(fixture.phase).toBe("D");
  expect(fixture.schema).toMatch(/^f13_runtime_[a-f0-9]+$/);
  expect(new URL(fixture.base_url).hostname).toMatch(/^(localhost|127\.0\.0\.1)$/);
  expect(process.env.E2E_BASE_URL).toBe(fixture.base_url);
  const directory = join(fixture.evidence_dir, "ui-runtime");
  mkdirSync(directory, { recursive: true });
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const before = await (await page.request.get("/__f13/state")).json();
  expect(before.queue).toBe("postgresql");
  await page.goto("/app/");
  await page.getByLabel("Email").fill("123@example.com");
  await page.getByLabel("密碼").fill("123456");
  await page.getByRole("button", { name: "登入", exact: true }).click();
  await page.getByRole("link", { name: "F13 隔離驗收品牌", exact: true }).click();
  await page.getByRole("link", { name: "投放中心", exact: true }).click();
  await page.getByTestId("campaign-grid").getByText("F13 測試｜暫停活動", { exact: true }).click();
  const workspace = page.waitForResponse(response => response.url().endsWith("/reviews") && response.request().method() === "GET");
  await page.getByRole("button", { name: "成效", exact: true }).click();
  const reviews = (await (await workspace).json() as ReviewsData).reviews;
  const unknown = reviews.find(row => row.id === fixture.unknown_review_id);
  const waiting = reviews.find(row => row.id === fixture.b2_review_id);
  expect(unknown).toBeTruthy(); expect(waiting).toBeTruthy();
  await chooseHistory(page, unknown!, "結果尚未確認");
  await expect(page.getByRole("alert").filter({ hasText: "本次未自動重新呼叫 AI" })).toBeVisible();
  await expect(page.getByRole("region", { name: "本次建議", exact: true })).toHaveCount(0);
  const tracking = page.getByRole("region", { name: "持續追蹤", exact: true });
  await tracking.getByRole("button", { name: "查看同步、恢復與追蹤設定", exact: true }).click();
  await expect(tracking.getByText(/最近背景啟動紀錄：/)).not.toContainText("尚無紀錄");
  await expect(tracking.getByText(/關閉網頁不會停止背景工作/)).toBeVisible();
  await capture(page, directory, "unknown-preserved-and-recovered-service");

  await chooseHistory(page, waiting!, "資料不足，等待補齊");
  await expect(page.getByRole("heading", { name: "先補齊判讀依據", exact: true })).toBeVisible();
  const source = page.getByRole("region", { name: "新測試來源", exact: true });
  await expect(source).toBeVisible();
  await expect(source.getByRole("link", { name: "查看來源檢討與決定 →", exact: true })).toHaveAttribute("href", new RegExp(`review=${fixture.first_review_id}`));
  await expect(page.getByRole("region", { name: "本次建議", exact: true })).toHaveCount(0);
  await capture(page, directory, "B2-waiting-source");

  const settings = tracking.getByRole("button", { name: "查看同步、恢復與追蹤設定", exact: true });
  await expect(settings).toHaveAttribute("aria-expanded", "false");
  await settings.click();
  const monitorPath = `/review-monitors/${fixture.b2_entity_id}`;
  const paused = page.waitForResponse(response => response.url().endsWith(monitorPath) && response.request().method() === "PUT");
  await tracking.getByRole("button", { name: "暫停自動檢討", exact: true }).click();
  expect((await paused).ok()).toBe(true);
  await expect(tracking.getByText("追蹤條件已保存並重新讀回。", { exact: true })).toBeVisible();
  await tracking.getByRole("button", { name: "調整觀察與檢討天數", exact: true }).click();
  await tracking.getByRole("spinbutton", { name: "觀察天數", exact: true }).fill("5");
  await tracking.getByRole("spinbutton", { name: "檢討間隔（天）", exact: true }).fill("2");
  const save = page.waitForResponse(response => response.url().endsWith(monitorPath) && response.request().method() === "PUT");
  await tracking.getByRole("button", { name: "保存追蹤條件", exact: true }).click();
  const saved = await save;
  expect(saved.ok(), await saved.text()).toBe(true);
  expect(saved.request().postDataJSON()).toMatchObject({ enabled: false, window_days: 5, cadence_days: 2, reset_window: false });
  await expect(tracking.getByText("追蹤條件已保存並重新讀回。", { exact: true })).toBeVisible();
  const reopened = page.waitForResponse(response => response.url().endsWith("/runtime") && response.request().method() === "GET");
  await page.reload();
  const persisted = (await (await reopened).json()) as RuntimeData;
  const monitor = persisted.monitors.find(row => row.entity_id === fixture.b2_entity_id);
  expect(monitor).toMatchObject({ enabled: false, window_days: 5, cadence_days: 2 });
  await tracking.getByRole("button", { name: "查看同步、恢復與追蹤設定", exact: true }).click();
  await expect(tracking.getByText(/每 2 天檢查，觀察最近 5 個完整日期/)).toBeVisible();
  await capture(page, directory, "monitor-saved-reopened");
  const resumed = page.waitForResponse(response => response.url().endsWith(monitorPath) && response.request().method() === "PUT");
  await tracking.getByRole("button", { name: "恢復自動檢討", exact: true }).click();
  expect((await resumed).ok()).toBe(true);
  await expect(tracking.getByText("追蹤條件已保存並重新讀回。", { exact: true })).toBeVisible();
  await tracking.getByRole("button", { name: "更新追蹤進度", exact: true }).click();
  await expect(page.getByRole("heading", { name: "先補齊判讀依據", exact: true })).toBeVisible();
  await capture(page, directory, "monitor-resumed-waiting");
  const after = await (await page.request.get("/__f13/state")).json();
  expect(after.provider_calls).toBe(before.provider_calls);
  expect(after.blocked_external).toBe(before.blocked_external);
  expect(errors).toEqual([]);
  writeFileSync(join(directory, "ui-receipt.json"), JSON.stringify({
    campaign_id: fixture.imported_campaign_id, entity_id: fixture.b2_entity_id,
    ui_submissions: ["pause monitor", "save 5-day window and 2-day cadence", "reopen saved preferences", "resume monitor"],
    persisted_monitor: monitor, provider_calls_delta: 0, page_errors: errors,
    boundary: "Recovery faults and source data were prepared by the isolated API runner; these monitor preferences were saved through the normal UI.",
  }, null, 2));
});
