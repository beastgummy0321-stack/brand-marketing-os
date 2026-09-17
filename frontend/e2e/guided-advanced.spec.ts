import { expect, test, type Page } from "@playwright/test";

type ApiHeaders = Record<string, string>;
type Coordinate = { dimension: string; key: string };
type Campaign = { id: string; groups: { id: string; name: string; ads: { id: string }[] }[] };

const DIMENSIONS = ["audience", "pain", "angle", "hook", "proof", "offer", "format"] as const;
const EVIDENCE_DIR = process.env.F12_EVIDENCE_DIR;

function dateOffset(days: number): string {
  const date = new Date();
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

async function register(page: Page, prefix: string): Promise<ApiHeaders> {
  const stamp = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const overviewRequest = page.waitForRequest((request) =>
    request.url().includes("/api/dashboard/overview") && Boolean(request.headers().authorization),
  );
  await page.goto("/app/login");
  await page.getByRole("button", { name: "還沒有帳號？註冊新帳號" }).click();
  await page.getByLabel("Email").fill(`${prefix}-${stamp}@example.com`);
  await page.getByLabel("密碼").fill(`guided-password-${stamp}`);
  await page.getByRole("button", { name: "註冊", exact: true }).click();
  await expect(page.getByRole("link", { name: "新增品牌" }).first()).toBeVisible();
  const headers = (await overviewRequest).headers();
  return Object.fromEntries(
    [["authorization", headers.authorization], ["x-org-id", headers["x-org-id"]]]
      .filter((entry): entry is [string, string] => Boolean(entry[1])),
  );
}

async function createBrand(page: Page, name: string): Promise<string> {
  await page.getByRole("link", { name: "新增品牌" }).first().click();
  await page.getByLabel("品牌名稱（必填）").fill(name);
  await page.getByRole("radio", { name: "完全沒投放過" }).check();
  await page.getByRole("button", { name: "建立品牌並開始初掃" }).click();
  await expect(page).toHaveURL(/\/app\/brands\/brd_.+\/intake/);
  return new URL(page.url()).pathname.split("/")[3];
}

async function api<T>(page: Page, headers: ApiHeaders, method: string, path: string, data?: unknown): Promise<T> {
  const response = await page.request.fetch(path, { method, headers, data });
  const text = await response.text();
  expect(response.ok(), `${method} ${path} failed: ${response.status()} ${text}`).toBeTruthy();
  return text ? JSON.parse(text) as T : {} as T;
}

async function assertNoHorizontalOverflow(page: Page, label: string) {
  const size = await page.evaluate(() => {
    const viewport = window.innerWidth;
    const overflow = Array.from(document.querySelectorAll<HTMLElement>("body *"))
      .map((element) => {
        const rect = element.getBoundingClientRect();
        return {
          tag: element.tagName.toLowerCase(),
          text: (element.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 100),
          className: element.className.toString().slice(0, 160),
          left: Math.round(rect.left),
          right: Math.round(rect.right),
          width: Math.round(rect.width),
        };
      })
      .filter((entry) => entry.right > viewport + 1)
      .sort((a, b) => b.right - a.right)
      .slice(0, 8);
    return { root: document.getElementById("root")?.scrollWidth ?? 0, viewport, overflow };
  });
  expect(
    size.root,
    `${label}: root scrollWidth ${size.root} > viewport ${size.viewport}; offenders=${JSON.stringify(size.overflow)}`,
  ).toBeLessThanOrEqual(size.viewport);
}

async function captureEvidence(page: Page, name: string) {
  if (!EVIDENCE_DIR) return;
  await page.screenshot({ path: `${EVIDENCE_DIR}/${name}.png` });
}

async function captureDesktopEvidence(page: Page, name: string) {
  for (const viewport of [
    { width: 1920, height: 1080 },
    { width: 1024, height: 768 },
  ]) {
    await page.setViewportSize(viewport);
    await captureEvidence(page, `${name}-${viewport.width}`);
    await assertNoHorizontalOverflow(page, `${name} ${viewport.width}`);
  }
}

async function createCampaignInUi(page: Page, brandId: string): Promise<string> {
  await page.goto(`/app/brands/${brandId}/ads/new`);
  await page.getByLabel("你這次想做到什麼？").fill("測試新品購買成效，保持平台與素材條件可核對。");
  await page.getByRole("button", { name: "日期" }).click();
  await page.getByLabel("開始日期").fill(dateOffset(-6));
  await page.getByLabel("結束日期").fill(dateOffset(0));
  await page.getByRole("button", { name: "產生建議", exact: true }).click();
  await expect(page.getByRole("heading", { name: "行銷駕駛艙理解如下" })).toBeVisible();
  await expect(page.getByText("商品", { exact: true })).toBeVisible();
  await expect(page.getByText("目標", { exact: true })).toBeVisible();
  await expect(page.getByText("預算", { exact: true })).toBeVisible();
  await expect(page.getByText("時間", { exact: true })).toBeVisible();
  await captureDesktopEvidence(page, "campaign-understood");
  const campaignId = new URL(page.url()).pathname.split("/").pop()!;
  await page.getByRole("button", { name: "產生策略建議 →" }).click();
  await expect(page).toHaveURL(new RegExp(`/app/brands/${brandId}/ads/campaigns/${campaignId}\\?tab=strategy`));
  await expect(page.getByText("行銷駕駛艙建議這樣投")).toBeVisible();
  await expect(page.getByRole("button", { name: "調整建議" })).toHaveAttribute("aria-expanded", "false");
  await captureDesktopEvidence(page, "strategy-general");
  return campaignId;
}

async function setupAds(
  page: Page,
  headers: ApiHeaders,
  brandId: string,
  campaignId: string,
  withPair: boolean,
): Promise<{ groupId: string }> {
  const coordinates = await api<{ coordinates: Coordinate[] }>(
    page, headers, "GET", `/api/schedule/brands/${brandId}/coordinates`,
  );
  const values = Object.fromEntries(DIMENSIONS.map((dimension) => {
    const value = coordinates.coordinates.find((row) => row.dimension === dimension)?.key;
    expect(value, `missing ${dimension} coordinate`).toBeTruthy();
    return [dimension, value!];
  }));
  const alternateHook = coordinates.coordinates.find(
    (row) => row.dimension === "hook" && row.key !== values.hook,
  )?.key;
  expect(alternateHook, "missing alternate hook coordinate").toBeTruthy();

  const group = await api<{ group: { id: string } }>(
    page, headers, "POST", `/api/ads/brands/${brandId}/campaigns/${campaignId}/groups`,
    { name: "一般受眾", role: "new", daily_budget: 100 },
  );
  await api(page, headers, "POST", `/api/ads/brands/${brandId}/campaigns/${campaignId}/ads`, {
    group_id: group.group.id,
    name: "廣告 A",
    coordinates: values,
  });
  if (withPair) {
    await api(page, headers, "POST", `/api/ads/brands/${brandId}/campaigns/${campaignId}/ads`, {
      group_id: group.group.id,
      name: "廣告 B",
      coordinates: { ...values, hook: alternateHook },
    });
  }
  return { groupId: group.group.id };
}

test("一般流程保留必要操作；受控 loading/error、empty、深連結與支援寬度可用", async ({ page }) => {
  await register(page, "guided-general");
  const brandId = await createBrand(page, `引導流程空品牌 ${Date.now()}`);

  // Controlled UI-state proof only: this delay is not evidence of backend latency.
  let releaseSettings!: () => void;
  const settingsGate = new Promise<void>((resolve) => { releaseSettings = resolve; });
  await page.route("**/api/settings", async (route) => {
    const response = await route.fetch();
    await settingsGate;
    await route.fulfill({ response });
  }, { times: 1 });
  await page.goto("/app/settings");
  await expect(page.getByLabel("設定載入中")).toBeVisible();
  releaseSettings();
  await expect(page.getByRole("button", { name: "品牌 AI 費用上限" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText("整個組織本月 AI 費用")).toBeVisible();
  await expect(page.getByRole("button", { name: "Meta 廣告連線" })).toBeVisible();

  // Controlled UI-state proof only: this synthetic 500 is not a real service/data failure.
  await page.goto(`/app/brands/${brandId}/library`);
  await page.route("**/api/settings", (route) => route.fulfill({
    status: 500,
    contentType: "application/json",
    body: JSON.stringify({ error: { message: "受控錯誤" } }),
  }), { times: 1 });
  await page.goto("/app/settings");
  await expect(page.getByRole("alert")).toContainText("設定讀取失敗");
  await page.getByRole("button", { name: "重新載入" }).click();
  await expect(page.getByText("整個組織本月 AI 費用")).toBeVisible();

  const advanced = page.getByText("進階設定");
  await advanced.focus();
  await page.keyboard.press("Enter");
  await expect(advanced.locator("..")).toHaveAttribute("open", "");
  await page.getByRole("button", { name: "模型設定" }).click();
  await expect(page).toHaveURL(/\/app\/settings\?tab=models/);

  await page.goto(`/app/brands/${brandId}/library`);
  await expect(page.getByRole("button", { name: /^品牌事實 \d+$/ })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: /^宣稱 \d+$/ })).toBeVisible();
  await expect(page.getByText("進階內容").locator("..")).not.toHaveAttribute("open", "");
  await page.goto(`/app/brands/${brandId}/library?tab=coordinates`);
  await expect(page.getByText("進階內容").locator("..")).toHaveAttribute("open", "");
  await expect(page.getByRole("button", { name: "創意座標" })).toHaveAttribute("aria-pressed", "true");

  await page.goto(`/app/brands/${brandId}/workbench`);
  await expect(page.getByText("目前沒有任務包")).toBeVisible();
  await page.goto(`/app/brands/${brandId}/ads`);
  await expect(page.getByText("還沒有 Campaign")).toBeVisible();

  for (const viewport of [
    { width: 1920, height: 1080, label: "wide" },
    { width: 1024, height: 768, label: "desktop" },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto("/app/settings");
    await expect(page.getByRole("heading", { name: "花費上限", exact: true })).toBeVisible();
    await captureEvidence(page, `settings-${viewport.width}`);
    await assertNoHorizontalOverflow(page, `settings ${viewport.label}`);
    await page.goto(`/app/brands/${brandId}/library?tab=coordinates`);
    await expect(page.getByRole("button", { name: "創意座標" })).toBeVisible();
    await captureEvidence(page, `library-coordinates-${viewport.width}`);
    await assertNoHorizontalOverflow(page, `library coordinates ${viewport.label}`);
  }
});

test("進階草稿真實保存回讀、比較選用與缺漏定位；普通品牌沒有內部入口", async ({ page }) => {
  test.setTimeout(120_000);
  const headers = await register(page, "guided-advanced");
  const brandId = await createBrand(page, `引導進階測試品牌 ${Date.now()}`);
  const campaignId = await createCampaignInUi(page, brandId);
  const { groupId } = await setupAds(page, headers, brandId, campaignId, true);

  await page.goto(`/app/brands/${brandId}/ads/campaigns/${campaignId}?tab=structure`);
  const missingButton = page.getByRole("button", { name: "補齊一般受眾設定" });
  await missingButton.focus();
  await page.keyboard.press("Enter");
  const audience = page.getByRole("textbox", { name: "受眾來源與納入條件 *" });
  await expect(audience).toBeFocused();
  await audience.fill("新客網站訪客，排除近 30 天購買者");
  await page.getByRole("button", { name: /人工上架設定與平台對應 · 有未儲存變更/ }).click();
  await expect(audience).toBeHidden();
  await page.getByRole("button", { name: /人工上架設定與平台對應 · 有未儲存變更/ }).click();
  await expect(audience).toHaveValue("新客網站訪客，排除近 30 天購買者");

  await page.goto(`/app/brands/${brandId}/library`);
  await page.goto(`/app/brands/${brandId}/ads/campaigns/${campaignId}?tab=structure`);
  await page.getByRole("button", { name: /人工上架設定與平台對應 · 有未儲存變更/ }).click();
  await page.getByRole("button", { name: /一般受眾 · 有未儲存變更/ }).click();
  await expect(page.getByText(/已恢復未儲存草稿/)).toBeVisible();
  await expect(audience).toHaveValue("新客網站訪客，排除近 30 天購買者");
  await page.getByRole("button", { name: "儲存這組設定" }).click();
  await expect(page.getByText("設定已儲存")).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: /人工上架設定與平台對應/ }).click();
  await page.getByRole("button", { name: /一般受眾 · 待補設定/ }).click();
  await expect(page.getByRole("textbox", { name: "受眾來源與納入條件 *" }))
    .toHaveValue("新客網站訪客，排除近 30 天購買者");
  await captureDesktopEvidence(page, "manual-launch-settings");

  await page.getByRole("button", { name: "素材", exact: true }).click();
  await expect(page.getByText("0／2 則已就位")).toBeVisible();
  await expect(page.getByText("未開始", { exact: true }).first()).toBeVisible();

  let simulationReads = 0;
  page.on("request", (request) => {
    if (/\/simulation\/\d{4}-\d{2}-\d{2}$/.test(request.url())) simulationReads += 1;
  });
  await page.getByRole("button", { name: "成效", exact: true }).click();
  await expect(page.getByRole("button", { name: "素材比較（選用）" })).toBeVisible();
  await expect(page.getByRole("button", { name: "內部驗收工具（隔離模擬）" })).toHaveCount(0);
  expect(simulationReads).toBe(0);
  await captureDesktopEvidence(page, "performance-general");

  await page.getByRole("button", { name: "素材比較（選用）" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText(/唯一變因/).first()).toBeVisible();
  await expect(page.getByText(/生效值：至少 7 天/)).toBeVisible();
  await page.getByRole("button", { name: "進階判讀設定" }).click();
  await page.getByRole("spinbutton", { name: "最少觀察天數" }).fill("5");
  await page.getByRole("spinbutton", { name: "相對差異門檻" }).fill("0.2");
  await page.getByRole("button", { name: "儲存比較設定" }).click();
  await expect(page.getByText(/生效值：至少 5 天/)).toBeVisible();
  await expect(page.getByText(/相對差異 20%/)).toBeVisible();

  const minDaysRow = page.getByRole("spinbutton", { name: "最少觀察天數" })
    .locator("xpath=ancestor::div[contains(@class, 'rounded-md')][1]");
  await minDaysRow.getByRole("button", { name: "恢復此項預設" }).click();
  await page.getByRole("button", { name: "儲存比較設定" }).click();
  await expect(page.getByText(/生效值：至少 7 天/)).toBeVisible();
  await expect(page.getByText(/相對差異 20%/)).toBeVisible();

  await page.getByRole("spinbutton", { name: "每則最少轉換數" }).fill("12");
  await page.goto(`/app/brands/${brandId}/ads/campaigns/${campaignId}?tab=overview`);
  await page.goto(`/app/brands/${brandId}/ads/campaigns/${campaignId}?tab=performance`);
  await expect(page.getByText(/已恢復未儲存的比較設定草稿/)).toBeVisible();
  await page.getByRole("button", { name: "素材比較（選用）" }).click();
  await page.getByRole("button", { name: "進階判讀設定" }).click();
  await expect(page.getByRole("spinbutton", { name: "每則最少轉換數" })).toHaveValue("12");
  await page.getByRole("button", { name: "取消設定變更" }).click();
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "確認這份比較計畫" }).click();
  await expect(page.getByText(/已確認；目前判讀/)).toBeVisible();

  for (const viewport of [
    { width: 1920, height: 1080, label: "wide comparison" },
    { width: 1024, height: 768, label: "desktop comparison" },
  ]) {
    await page.setViewportSize(viewport);
    await captureEvidence(page, `comparison-confirmed-${viewport.width}`);
    await assertNoHorizontalOverflow(page, viewport.label);
    await expect(page.getByText(/作用範圍：這個 Campaign；版本/)).toBeVisible();
  }

  const missingCampaign = await api<{ campaign: Campaign }>(
    page, headers, "POST", `/api/ads/brands/${brandId}/campaigns`, {
      goal_text: "建立只有一則廣告的缺漏定位測試",
      start_date: dateOffset(-6),
      end_date: dateOffset(0),
    },
  );
  await setupAds(page, headers, brandId, missingCampaign.campaign.id, false);
  await page.goto(`/app/brands/${brandId}/ads/campaigns/${missingCampaign.campaign.id}?tab=performance`);
  await page.getByRole("button", { name: "素材比較（選用）" }).click();
  await expect(page.getByText(/缺少合格對照/)).toBeVisible();
  await page.getByRole("button", { name: "前往投放結構補對照" }).click();
  await expect(page).toHaveURL(new RegExp(`campaigns/${missingCampaign.campaign.id}\\?tab=structure`));

  // The local-only public acceptance seam permanently isolates only this newly-created test brand.
  await api(page, headers, "POST", `/api/ads/brands/${brandId}/campaigns/${campaignId}/simulation/start`, {
    confirm_isolation: true,
  });
  simulationReads = 0;
  await page.goto(`/app/brands/${brandId}/ads/campaigns/${campaignId}?tab=performance`);
  const internal = page.getByRole("button", { name: "內部驗收工具（隔離模擬）" });
  await expect(internal).toBeVisible();
  expect(simulationReads).toBe(0);
  await internal.click();
  await expect.poll(() => simulationReads).toBe(1);
  await page.getByText("隔離模擬成效回收", { exact: true }).click();
  await expect(page.getByText(/隔離模擬已啟用/)).toBeVisible();

  // Setup used public surfaces and this assertion keeps the exact created group tied to our campaign.
  const stored = await api<{ campaign: Campaign }>(
    page, headers, "GET", `/api/ads/brands/${brandId}/campaigns/${campaignId}`,
  );
  expect(stored.campaign.groups.some((group) => group.id === groupId)).toBeTruthy();
});
