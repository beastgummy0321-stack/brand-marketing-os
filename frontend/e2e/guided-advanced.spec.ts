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
  await page.getByLabel("品牌名稱", { exact: true }).fill(name);
  await page.getByRole("radio", { name: "完全沒投過" }).check();
  await page.getByRole("button", { name: "下一步 →" }).click();
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

async function openPerformanceDetails(page: Page) {
  // F30-I07: the platform charts moved into the perf tab's 進階 fold (F40-I06 label: 每日資料、次要指標與舊版檢討).
  const details = page.getByRole("button", { name: "進階：每日資料、次要指標與舊版檢討", exact: true });
  await expect(details).toHaveAttribute("aria-expanded", "false");
  await details.click();
  await expect(details).toHaveAttribute("aria-expanded", "true");
}

async function createCampaignInUi(page: Page, headers: ApiHeaders, brandId: string): Promise<string> {
  // F30-I05: the wizard picks one of the brand's products. F43-I04: only a finished sell-way is pickable, so the
  // product is built through product onboarding (create → 賣法與價格 → 完成; synchronous, no spend).
  const productName = "引導測試新品 500ml";
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
  await page.goto(`/app/brands/${brandId}/ads/new`);
  // F43-I15: 要推什麼 lists the product as a section and its sell-way as the card (「單品 NT$1,580」).
  const shelf = page.getByRole("radiogroup", { name: "要推什麼" });
  await expect(shelf.getByText(productName, { exact: true })).toBeVisible();
  await shelf.getByRole("radio", { name: /^單品 1,580 TWD/ }).click();
  await page.getByRole("radio", { name: /^購買/ }).click();
  await page.getByLabel("開始", { exact: true }).fill(dateOffset(-6));
  await page.getByLabel("結束", { exact: true }).fill(dateOffset(0));
  await page.getByLabel("這個活動最多花").fill("30000");
  await page.getByRole("button", { name: "下一步：系統理解 →", exact: true }).click();
  await expect(page.getByRole("heading", { name: "系統這樣理解" })).toBeVisible();
  // The brief's row labels, read inside the page: the shell's sidebar also has a 「商品」 link (F43-I14).
  const main = page.getByRole("main");
  await expect(main.getByText("商品", { exact: true })).toBeVisible();
  await expect(main.getByText("結果", { exact: true })).toBeVisible();
  await expect(main.getByText("預算上限", { exact: true })).toBeVisible();
  await expect(main.getByText("期間", { exact: true })).toBeVisible();
  await captureDesktopEvidence(page, "campaign-understood");
  const campaignId = new URL(page.url()).pathname.split("/").pop()!;
  await page.getByRole("button", { name: "產生策略 →" }).click();
  await expect(page).toHaveURL(new RegExp(`/app/brands/${brandId}/ads/campaigns/${campaignId}\\?tab=strategy`));
  // F28-I09: the strategy tab is 一個上限 → 這一期的總預算 → 預算怎麼分; the reasons sit in a fold that starts closed.
  await expect(page.getByRole("heading", { name: "一個上限", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "這一期的總預算", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "為什麼這樣建議", exact: true })).toHaveAttribute("aria-expanded", "false");
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
  // F48-I06: a hand-made ad obeys this period's menu (the campaign read serves it); a vocabulary
  // key the menu leaves out (e.g. a proof the brand has no evidence for) is refused with a 400.
  const { campaign } = await api<{ campaign: { menu: Coordinate[] } }>(
    page, headers, "GET", `/api/ads/brands/${brandId}/campaigns/${campaignId}`,
  );
  const menu = campaign.menu;
  const values = Object.fromEntries(DIMENSIONS.map((dimension) => {
    const value = menu.find((row) => row.dimension === dimension)?.key;
    expect(value, `missing ${dimension} coordinate`).toBeTruthy();
    return [dimension, value!];
  }));
  const alternateHook = menu.find(
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
  // F47-I02: the server sentence wins over the status-code fallback.
  await expect(page.getByRole("alert")).toContainText("受控錯誤");
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
  // F28-I08: a brand with no campaign gets one honest empty card (no money, band or decisions that could only print
  // zeros) whose one primary action is ＋ 建立活動.
  const empty = page.getByRole("region", { name: "還沒有進行中的活動" });
  await expect(empty).toBeVisible();
  await expect(empty.getByRole("link", { name: "建立活動", exact: true })).toHaveAttribute("href", `/app/brands/${brandId}/ads/new`);
  await expect(page.getByRole("link", { name: "建立活動", exact: true })).toHaveCount(1);
  await expect(page.getByText("的廣告費花得划算")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: /^需要你決定/ })).toHaveCount(0);

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
  const campaignId = await createCampaignInUi(page, headers, brandId);
  const { groupId } = await setupAds(page, headers, brandId, campaignId, true);

  await page.goto(`/app/brands/${brandId}/ads/campaigns/${campaignId}?tab=structure`);
  // F30-I08: a group's manual settings live in its fold 「進階：編輯這一組（…）」, in the sub-fold 「人工上架設定」.
  const groupFold = page.getByRole("button", { name: /^進階：編輯這一組（一般受眾）/ });
  await groupFold.click();
  const missingButton = page.getByRole("button", { name: "補齊一般受眾設定" });
  await missingButton.focus();
  await page.keyboard.press("Enter");
  // F29 Unresolved 5: the landing URL is still required; the audience source became optional, so the jump lands on
  // the landing URL (追蹤 section). The jump switches the section once; the user can then open 受眾 and stay there.
  await expect(page.getByRole("textbox", { name: "落地頁網址 *" })).toBeFocused();
  await page.getByLabel("設定分類").getByRole("button", { name: "受眾", exact: true }).click();
  const audience = page.getByRole("textbox", { name: "受眾來源與納入條件", exact: true });
  await audience.fill("新客網站訪客，排除近 30 天購買者");
  await page.getByRole("button", { name: "人工上架設定 · 有未儲存變更" }).click();
  await expect(audience).toBeHidden();
  await page.getByRole("button", { name: "人工上架設定 · 有未儲存變更" }).click();
  await expect(audience).toHaveValue("新客網站訪客，排除近 30 天購買者");

  await page.goto(`/app/brands/${brandId}/library`);
  await page.goto(`/app/brands/${brandId}/ads/campaigns/${campaignId}?tab=structure`);
  await groupFold.click();
  await page.getByRole("button", { name: "人工上架設定 · 有未儲存變更" }).click();
  await expect(page.getByText(/已恢復未儲存草稿/)).toBeVisible();
  await expect(audience).toHaveValue("新客網站訪客，排除近 30 天購買者");
  await page.getByRole("button", { name: "儲存這組設定" }).click();
  await expect(page.getByText("設定已儲存")).toBeVisible();
  await page.reload();
  await groupFold.click();
  await page.getByRole("button", { name: /^人工上架設定 · 待補設定/ }).click();
  await expect(page.getByRole("textbox", { name: "受眾來源與納入條件", exact: true }))
    .toHaveValue("新客網站訪客，排除近 30 天購買者");
  await captureDesktopEvidence(page, "manual-launch-settings");

  await page.getByRole("button", { name: "素材", exact: true }).click();
  // F30-I11: the old panels live in the tab's 「進階」 fold.
  await page.getByRole("button", { name: "進階：素材需求、自帶素材與人工交接", exact: true }).click();
  const legacyMaterials = page.getByRole("button", { name: "原有任務包與平台素材", exact: true });
  await expect(legacyMaterials).toHaveAttribute("aria-expanded", "false");
  await legacyMaterials.click();
  await expect(legacyMaterials).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByText("0／2 則素材已備妥")).toBeVisible();
  await expect(page.getByText("未開始", { exact: true }).first()).toBeVisible();

  let simulationReads = 0;
  page.on("request", (request) => {
    if (/\/simulation\/\d{4}-\d{2}-\d{2}$/.test(request.url())) simulationReads += 1;
  });
  await page.getByRole("button", { name: "成效", exact: true }).click();
  await openPerformanceDetails(page);
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
  await openPerformanceDetails(page);
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
  await openPerformanceDetails(page);
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
  await openPerformanceDetails(page);
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
