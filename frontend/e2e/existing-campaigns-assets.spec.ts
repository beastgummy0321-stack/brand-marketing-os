import { expect, test, type Page, type Locator } from "@playwright/test";
import { readFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";

/** Requires the isolated F13 server with real job handlers and Storage.
 * Ordinary smoke uses a non-executing queue, so it cannot prove this flow. */
interface Context {
  base_url: string;
  brand_id: string;
  org_id: string;
  imported_campaign_id: string;
  second_brand_id: string;
  media_paths: { image: string; video: string; corrupt: string };
  evidence_dir?: string;
  browser_native_id?: string;
}
const contextPath = process.env.F13_E2E_CONTEXT;
test.skip(!contextPath, "F13 needs its isolated runtime server; run the --browser fixture lifecycle.");

// Valid ancillary PNG / MP4 boxes give each synthetic file a distinct hash.
function uniqueMedia(bytes: Buffer, kind: "png" | "mp4", tag: string) {
  const data = Buffer.from(`F13\0${tag}`);
  if (kind === "mp4") {
    const box = Buffer.alloc(8); box.writeUInt32BE(8 + data.length); box.write("free", 4);
    return Buffer.concat([bytes, box, data]);
  }
  const payload = Buffer.concat([Buffer.from("tEXt"), data]);
  let crc = 0xffffffff;
  for (const byte of payload) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
  }
  const length = Buffer.alloc(4); length.writeUInt32BE(data.length);
  const checksum = Buffer.alloc(4); checksum.writeUInt32BE((crc ^ 0xffffffff) >>> 0);
  expect(bytes.subarray(-8, -4).toString()).toBe("IEND");
  return Buffer.concat([bytes.subarray(0, -12), length, payload, checksum, bytes.subarray(-12)]);
}

async function capture(page: Page, directory: string, state: string, focus?: Locator) {
  for (const width of [1024, 1920]) {
    await page.setViewportSize({ width, height: 1080 });
    await page.evaluate(() => window.scrollTo(0, 0));
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 2)).toBe(true);
    await page.screenshot({ path: join(directory, `${state}-${width}.png`), fullPage: true });
    if (focus) await focus.screenshot({ path: join(directory, `${state}-card-${width}.png`) });
  }
}

test("existing campaign, originals, confirmation and version evidence survive reopening", async ({ page }) => {
  test.setTimeout(300_000);
  if (!contextPath) throw new Error("Missing F13 fixture context");
  const fixture = JSON.parse(readFileSync(contextPath, "utf8")) as Context;
  expect(new URL(fixture.base_url).hostname).toMatch(/^(localhost|127\.0\.0\.1)$/);
  expect(process.env.E2E_BASE_URL).toBe(fixture.base_url);
  const evidence = fixture.evidence_dir ?? join(dirname(contextPath), "screenshots");
  mkdirSync(evidence, { recursive: true });
  const root = `/app/brands/${fixture.brand_id}/ads`;
  const browserErrors: string[] = [];
  page.on("pageerror", error => browserErrors.push(error.message));
  await page.goto("/app/login");
  await page.getByLabel("Email").fill("123@example.com");
  await page.getByLabel("密碼").fill("123456");
  await page.getByRole("button", { name: "登入", exact: true }).click();
  await expect(page).not.toHaveURL(/\/login/);
  // Test-source revision makes reruns independent; only real sync handlers update bindings.
  const sourceChange = await page.request.post("/__f13/state", { data: { creative_revision: Date.now() } });
  expect(sourceChange.ok()).toBe(true);

  await page.goto(root);
  await page.getByRole("button", { name: "加入既有活動", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("button", { name: "納入並開啟" }).first()).toBeEnabled({ timeout: 30_000 });
  await dialog.getByRole("button", { name: "納入並開啟" }).first().click();
  await expect(page).toHaveURL(/\/ads\/campaigns\/[^?]+/);
  const campaignUrl = new URL(page.url()).pathname;
  await expect(page.getByRole("heading", { name: "狀態時間軸" })).toBeVisible();
  await page.getByRole("button", { name: "重新讀取平台", exact: true }).click();
  await expect(page.getByRole("button", { name: "同步中…", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "重新讀取平台", exact: true })).toBeEnabled({ timeout: 30_000 });
  await page.getByRole("button", { name: "策略", exact: true }).click();
  await page.getByRole("button", { name: "進階設定", exact: true }).click();
  await page.getByLabel("內部活動目標", { exact: true }).fill(`介紹品牌產品 ${Date.now()}`);
  await page.getByRole("button", { name: "儲存目標", exact: true }).click();
  await expect(page.getByRole("button", { name: "儲存目標", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "投放結構", exact: true }).click();
  await page.getByRole("button", { name: "調整結構（進階）", exact: true }).click();
  await expect(page.getByRole("heading", { name: "投放結構", exact: true })).toBeVisible();
  await capture(page, evidence, "existing-native");

  await page.goto(`${campaignUrl}?tab=assets`);
  await expect(page.getByRole("heading", { name: "自帶素材安排" })).toBeVisible();
  const stamp = Date.now();
  const imageName = `browser-${stamp}-0.png`;
  const videoName = `browser-${stamp}.mp4`;
  const copy = { headline: "產品介紹", body: "了解品牌產品", description: "查看產品資訊" };
  const imageBytes = readFileSync(fixture.media_paths.image);
  const files = Array.from({ length: 11 }, (_, i) => ({ name: `browser-${stamp}-${i}.png`, mimeType: "image/png", buffer: uniqueMedia(imageBytes, "png", `${stamp}-${i}`) }));
  files.push({ name: videoName, mimeType: "video/mp4", buffer: uniqueMedia(readFileSync(fixture.media_paths.video), "mp4", String(stamp)) });
  await page.getByLabel("選擇自帶素材", { exact: true }).setInputFiles(files);
  for (const { name } of files) {
    for (const [field, label] of [["headline", "標題"], ["body", "內文"], ["description", "說明"]] as const) {
      if (name === imageName && field === "description") continue;
      await page.getByLabel(`${name}原文${label}`, { exact: true }).fill(copy[field]);
    }
  }
  await page.getByRole("button", { name: "保存原檔與原文" }).click();
  await expect(page.getByText(/處理中，完成原檔/)).toHaveCount(0, { timeout: 30_000 });
  for (const { name } of files) {
    const row = page.locator("div.flex.flex-col.gap-2.py-3").filter({ has: page.getByText(name, { exact: true }) });
    await expect(row.getByText("原檔已保存", { exact: true })).toBeVisible();
    await row.getByRole("button", { name: "加入此活動（保留本批原文）" }).click();
  }
  await page.reload();
  await expect(page.getByRole("heading", { name: "自帶素材安排" })).toBeVisible();
  const card = page.locator("article").filter({ has: page.getByRole("heading", { name: new RegExp(`^${imageName.replaceAll(".", "\\.")} ·`) }) });
  await expect(card).toBeVisible();
  await capture(page, evidence, "heavy-required-pending");
  await card.getByText(/編輯原文與內部安排/).click();
  const titleInput = card.locator("textarea").first();
  await expect(titleInput).toHaveValue(copy.headline);
  await card.locator('input[aria-label$="用途"]').fill("產品介紹");
  await card.getByRole("button", { name: "儲存為新版安排" }).click();
  await expect(card.getByText("有未儲存編輯")).toHaveCount(0);
  // Previews complete through the real background handler, then a normal reload reads them.
  await expect(async () => {
    await page.getByRole("button", { name: "重新讀取安排", exact: true }).click();
    await expect(card.getByText("原檔預覽完成", { exact: false })).toBeVisible();
  }).toPass({ timeout: 30_000 });
  await card.getByRole("checkbox", { name: `納入建議 ${imageName}`, exact: true }).check();
  await page.getByRole("button", { name: "為選取 1 件取得建議", exact: true }).click();
  await expect(card.getByRole("button", { name: "核對後確認這件建議" })).toBeEnabled({ timeout: 30_000 });
  await card.getByRole("button", { name: "核對後確認這件建議" }).click();
  const confirmed = card;
  await expect(confirmed).toBeVisible();
  await confirmed.getByRole("button", { name: "手動交接與平台核對", exact: true }).click();
  await expect(confirmed.getByText(/廣告存在、素材版本與成效歸屬/)).toBeVisible();
  await confirmed.getByRole("button", { name: "查看預覽", exact: true }).click();
  await expect.poll(async () => {
    const img = confirmed.locator('img[src^="blob:"]');
    if (await img.count()) return img.first().evaluate(node => (node as HTMLImageElement).naturalWidth > 0);
    const video = confirmed.locator("video");
    return await video.count() ? video.first().evaluate(node => (node as HTMLVideoElement).readyState >= 1) : false;
  }).toBe(true);
  await confirmed.getByRole("button", { name: "我已手動上架（僅自行回報）" }).click();
  await expect(confirmed.getByText("使用者自行回報，尚未由平台證實", { exact: false })).toBeVisible();
  const accounts = confirmed.getByLabel("核對平台帳號");
  await expect(accounts.locator("option")).not.toHaveCount(1);
  await accounts.selectOption({ index: 1 });
  await confirmed.getByRole("button", { name: "載入平台候選", exact: true }).click();
  const nativeCandidates = confirmed.getByLabel("選擇平台廣告");
  if (fixture.browser_native_id) {
    const option = nativeCandidates.locator("option").filter({ hasText: fixture.browser_native_id });
    await nativeCandidates.selectOption((await option.getAttribute("value"))!);
  } else await nativeCandidates.selectOption({ index: 1 });
  await confirmed.getByRole("button", { name: "重新讀回並核對廣告", exact: true }).click();
  await expect(confirmed.getByText(/平台已讀回廣告與父層關係/)).toBeVisible();
  await expect(confirmed.getByText(/尚未核對是否使用這一版素材/).first()).toBeVisible();
  await confirmed.getByText("檢查這一版的成效歸屬", { exact: true }).click();
  await confirmed.getByRole("button", { name: "讀取版本成效", exact: true }).click();
  await expect(confirmed.getByText(/不可歸屬本版：|版本成效未知/).first()).toBeVisible();
  await expect(confirmed.getByText("此筆觀測有足夠證據歸屬本版")).toHaveCount(0);
  await capture(page, evidence, "manual-handoff", confirmed);
  await page.reload();
  await confirmed.getByRole("button", { name: "手動交接與平台核對", exact: true }).click();
  await expect(confirmed.getByText(/平台已讀回廣告與父層關係/)).toBeVisible();
  await confirmed.getByText(/編輯原文與內部安排/).click();
  await confirmed.locator("textarea").first().fill("新版產品介紹");
  await confirmed.getByRole("button", { name: "儲存為新版安排" }).click();
  await expect(confirmed.getByRole("button", { name: "只用我的文案，檢查並確認" })).toBeVisible();
  await expect(confirmed.getByRole("button", { name: "手動交接與平台核對", exact: true })).toHaveCount(0);
  await expect(confirmed.getByRole("button", { name: /版歷史／結束對應/ })).toBeVisible();
  await capture(page, evidence, "revised-pending-history");

  const videoCard = page.locator("article").filter({ has: page.getByRole("heading", { name: new RegExp(`^${videoName.replaceAll(".", "\\.")} ·`) }) });
  await videoCard.getByText(/編輯原文與內部安排/).click();
  await videoCard.locator('input[aria-label$="用途"]').fill("產品介紹");
  await videoCard.getByRole("button", { name: "儲存為新版安排" }).click();
  await expect(videoCard.getByText("有未儲存編輯")).toHaveCount(0);
  await expect(async () => {
    await page.getByRole("button", { name: "重新讀取安排", exact: true }).click();
    await expect(videoCard.getByText("原檔預覽完成", { exact: false })).toBeVisible();
  }).toPass({ timeout: 30_000 });
  await videoCard.getByRole("button", { name: "只用我的文案，檢查並確認" }).click();
  await videoCard.getByRole("button", { name: "手動交接與平台核對", exact: true }).click();
  await videoCard.getByRole("button", { name: "查看預覽", exact: true }).click();
  await expect.poll(() => videoCard.locator("video").evaluate(node => (node as HTMLVideoElement).readyState)).toBeGreaterThanOrEqual(1);
  await capture(page, evidence, "playable-video", videoCard);

  // New campaign uses the same durable brand library, without generating a strategy.
  await page.goto(`${root}/new`);
  await expect(page.getByRole("heading", { name: "建立投放計畫" })).toBeVisible();
  await page.getByRole("checkbox", { name: `選取 ${imageName}`, exact: true }).check();
  await page.getByLabel("你這次想做到什麼？").fill("介紹品牌產品，希望增加購買");
  await page.getByRole("button", { name: "產生建議", exact: true }).click();
  await expect(page).toHaveURL(/\/ads\/new\/[^?]+/, { timeout: 30_000 });
  const newId = new URL(page.url()).pathname.split("/").at(-1);
  await page.goto(`${root}/campaigns/${newId}?tab=assets`);
  await expect(page.locator("article")).toHaveCount(1);
  await capture(page, evidence, "new-campaign-assets");

  // Transport fault injection verifies UI error/loading handling; no success is fabricated.
  const libraryPattern = "**/api/ads/brands/*/user-assets?*";
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route(libraryPattern, async route => { await gate; await route.continue(); });
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.getByText("讀取品牌素材中…", { exact: true })).toBeVisible();
  await capture(page, evidence, "loading-delayed-get");
  release();
  await page.unrouteAll({ behavior: "wait" });
  await expect(page.getByText("讀取品牌素材中…", { exact: true })).toHaveCount(0);
  await page.route(libraryPattern, route => route.abort("failed"));
  await page.getByRole("button", { name: "重新載入品牌素材" }).click();
  await expect(page.getByRole("alert").first()).toBeVisible();
  await capture(page, evidence, "error-aborted-get");
  await page.unroute(libraryPattern);
  await page.getByRole("button", { name: "重新載入品牌素材" }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await page.goto(`/app/brands/${fixture.second_brand_id}/ads/new`);
  await expect(page.getByText("品牌尚無自帶素材。加入原檔後可安排文案，不必先產生圖片。")).toBeVisible();
  await expect(page.getByText(imageName, { exact: true })).toHaveCount(0);
  await capture(page, evidence, "empty-other-brand");
  expect(browserErrors).toEqual([]);
});
