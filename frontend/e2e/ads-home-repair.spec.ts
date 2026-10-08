import { expect, test } from "@playwright/test";
import { HOME_PATH, homeMocks, type HomeScene } from "../src/components/ads/home/homeEvidence.fixtures";

/** Actual bundle, browser fixtures only. No platform writes or live worker claims. */
for (const width of [1024, 1920]) {
  test(`F54 home ${width}: source boundaries, execution health, keyboard and overflow`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 1200 });
    await page.goto("/app/login");
    await page.getByLabel("Email").fill("123@example.com");
    await page.getByLabel("密碼").fill("123456");
    await page.getByRole("button", { name: "登入", exact: true }).click();
    await page.waitForURL(url => !url.pathname.includes("/login"));
    let scene: HomeScene = "healthy";
    let healthFailed = false;
    let homeFailed = false;
    let partialQuality = false;
    let delayHome = false;
    let releaseHome: (() => void) | null = null;
    await page.route("**/api/**", route => route.abort());
    for (const glob of Object.keys(homeMocks())) {
      await page.route(glob, async route => {
        if (glob.includes("jobs/active") && healthFailed) return route.fulfill({ status: 503, json: { detail: "health unavailable" } });
        const json = homeMocks(scene)[glob as keyof ReturnType<typeof homeMocks>];
        if (glob.endsWith("/home*")) {
          if (delayHome) await new Promise<void>(resolve => { releaseHome = resolve; });
          if (homeFailed) return route.fulfill({ status: 503, json: { detail: "overview unavailable" } });
          if (partialQuality) (json as ReturnType<typeof homeMocks>["**/api/ads/brands/*/home*"]).quality = null;
        }
        return route.fulfill({ json });
      });
    }
    for (const next of ["healthy", "stopped", "unknown", "over-cap-zero-queue", "order-unknown", "pace-mismatch", "pace-unknown"] as const) {
      scene = next;
      healthFailed = next === "unknown";
      await page.goto(HOME_PATH);
      const body = page.locator("#main-content");
      await expect(body.getByText("已收集的已付款訂單淨額")).toBeVisible();
      if (next === "over-cap-zero-queue") {
        await expect(body.getByText("目前沒有待決定的項目")).toBeVisible();
        await expect(body.getByText("NT$500 元").first()).toBeVisible();
        await expect(body.getByText("上限 NT$100")).toBeVisible();
      } else {
        await expect(body.getByText("成本持續超過上限")).toBeVisible();
        await expect(body.getByRole("link", { name: "查原因 →" })).toHaveAttribute("href", /\/review\/ad_current$/);
      }
      if (next === "stopped" || next === "unknown") {
        await expect(body.getByText(next === "stopped" ? "背景執行已停止" : "背景狀態未確認")).toBeVisible();
        await expect(body.getByText(/下次同步預估/)).toHaveCount(0);
      }
      if (next === "order-unknown") await expect(body.getByText("目前無法確認訂單證據")).toBeVisible();
      else await expect(body.getByText("8 筆已付款・7 筆金額已知・1 筆已退款")).toBeVisible();
      if (next === "pace-mismatch" || next === "pace-unknown") {
        await expect(body.getByText("暫不比較", { exact: true })).toBeVisible();
        await expect(body.getByText("前期與本期成本幣別無法比較")).toBeVisible();
        await expect(body.getByText(/月底會用不完|月底會超出/)).toHaveCount(0);
        await expect(body.locator('[data-slot="pace-chart"]')).toHaveCount(0);
      }
      await expect(body.getByRole("button", { name: "平台購買假設估算" })).toHaveAttribute("aria-expanded", "false");
      expect(await body.locator('[data-slot="button"][data-variant="default"]').count()).toBeLessThanOrEqual(1);
      for (const locator of [page.locator("#root"), body, body.getByTestId("campaign-grid")]) {
        expect(await locator.evaluate(node => node.scrollWidth)).toBeLessThanOrEqual(await locator.evaluate(node => node.clientWidth));
      }
      await page.screenshot({ path: info.outputPath(`home-${next}-${width}.png`), fullPage: true });
    }
    const fold = page.getByRole("button", { name: "平台購買假設估算" });
    await fold.focus();
    await expect(fold).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(fold).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByText("平台購買數推估，不能當作已付款利潤")).toBeVisible();
    await page.keyboard.press("Enter");
    await expect(fold).toHaveAttribute("aria-expanded", "false");
    await expect(fold).toBeFocused();
    const source = page.getByRole("button", { name: "訂單來源與狀態" });
    await source.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByText("2 筆待付款・1 筆付款狀態未知")).toBeVisible();
    await expect(page.getByText("1 筆金額未知・1 筆取消或作廢")).toBeVisible();
    await page.screenshot({ path: info.outputPath(`home-source-details-${width}.png`), fullPage: true });
    await page.keyboard.press("Enter");
    await expect(source).toHaveAttribute("aria-expanded", "false");
    scene = "healthy"; healthFailed = false; partialQuality = true;
    await page.goto(HOME_PATH);
    await expect(page.getByRole("link", { name: "查原因 →" })).toBeVisible();
    delayHome = true;
    await page.getByRole("button", { name: "重試", exact: true }).click();
    await expect(page.getByText("正在更新，顯示上次資料")).toBeVisible();
    await expect(page.getByRole("link", { name: "查原因 →" })).toBeVisible();
    await page.screenshot({ path: info.outputPath(`home-reloading-${width}.png`), fullPage: true });
    await expect.poll(() => Boolean(releaseHome)).toBe(true);
    delayHome = false; homeFailed = true; releaseHome!();
    await expect(page.getByText(/更新失敗，顯示上次資料/)).toBeVisible();
    await expect(page.getByRole("link", { name: "查原因 →" })).toBeVisible();
    await page.screenshot({ path: info.outputPath(`home-refresh-error-${width}.png`), fullPage: true });
    homeFailed = false; partialQuality = false;
    await page.getByRole("button", { name: "重新讀取首頁" }).click();
    await expect(page.getByText(/更新失敗，顯示上次資料/)).toHaveCount(0);
    await expect(page.locator('[data-slot="grade-band"]')).toBeVisible();
  });
}
