import { expect, test } from "@playwright/test";

test("自訂看板可儲存、鍵盤排序，並與其他品牌隔離", async ({ page }) => {
  const stamp = Date.now();
  await page.goto("/app/login");
  await page.getByRole("button", { name: "還沒有帳號？註冊新帳號" }).click();
  await page.getByLabel("Email").fill(`layout-${stamp}@example.com`);
  await page.getByLabel("密碼").fill(`layout-password-${stamp}`);
  await page.getByRole("button", { name: "註冊", exact: true }).click();
  await page.getByRole("link", { name: "新增品牌" }).first().click();
  await page.getByLabel("品牌名稱（必填）").fill(`版面測試 A ${stamp}`);
  await page.getByRole("button", { name: "建立品牌並開始初掃" }).click();
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
  await page.getByLabel("品牌名稱（必填）").fill(`版面測試 B ${stamp}`);
  await page.getByRole("button", { name: "建立品牌並開始初掃" }).click();
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
