import { expect, test, type Locator, type Page, type Response } from "@playwright/test";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const contextPath = process.env.F15_C_E2E_CONTEXT;
test.skip(!contextPath, "Requires phase C isolated fixture server; never use real platform accounts.");
interface Fixture {
  base_url: string; schema: string; brand_id: string; evidence_dir: string;
  phase: string; next_material_task_id: string; material_task_id: string; reference_asset_id: string;
}
interface Task {
  id: string; revision: number; title: string; mode: string;
  prompt: { source: string; text?: string; version_id?: string };
  reference_asset_ids: string[]; copy_fields: { headline?: string; body?: string; description?: string };
  candidates: { id: string; asset_id: string; filename: string; prompt: { text?: string }; reference_asset_ids: string[] }[];
  selected_candidate_id: string | null; placement_id: string | null;
}
async function capture(page: Page, directory: string, state: string, previewNames: string[] = []) {
  const previews = [];
  for (const width of [1024, 1920]) {
    await page.setViewportSize({ width, height: 1080 });
    await page.evaluate(() => window.scrollTo(0, 0));
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 2)).toBe(true);
    const decoded = await Promise.all(previewNames.map(async filename => {
      const preview = page.getByRole("region", { name: "素材任務", exact: true }).getByRole("img", { name: filename, exact: true });
      await expect(preview).toBeVisible({ timeout: 60_000 });
      await expect.poll(() => preview.evaluate(element => {
        const image = element as HTMLImageElement;
        return image.complete && image.naturalWidth > 0 && image.naturalHeight > 0;
      }), { timeout: 60_000 }).toBe(true);
      return preview.evaluate(async element => {
        const image = element as HTMLImageElement;
        await image.decode();
        return { filename: image.alt, width: image.naturalWidth, height: image.naturalHeight };
      });
    }));
    if (decoded.length) previews.push({ viewport_width: width, decoded });
    await page.screenshot({ path: join(directory, `${state}-${width}.png`), fullPage: true });
  }
  return previews;
}
function responseFor(page: Page, suffix: string, method = "POST") {
  return page.waitForResponse(response => new URL(response.url()).pathname.endsWith(suffix) && response.request().method() === method);
}
async function taskResponse(response: Promise<Response>): Promise<Task> {
  const result = await response;
  expect(result.ok(), await result.text()).toBe(true);
  return (await result.json()).task as Task;
}
async function chooseStored(dialog: Locator, filename: string) {
  const checkbox = dialog.getByRole("checkbox", { name: `選取 ${filename}`, exact: true });
  for (let page = 0; page < 5 && await checkbox.count() === 0; page++) {
    const more = dialog.getByRole("button", { name: "載入更多上傳紀錄", exact: true });
    if (!await more.isVisible()) break;
    await more.click();
  }
  await checkbox.check();
}

test("C: normal entry, existing assets, P2/R and ten candidates, then a saved copy version to approval", async ({ page }) => {
  test.setTimeout(240_000);
  if (!contextPath) throw new Error("Missing isolated fixture context");
  const fixture = JSON.parse(readFileSync(contextPath, "utf8")) as Fixture;
  expect(fixture.schema).toMatch(/^f13_runtime_[a-f0-9]+$/);
  expect(fixture.phase).toBe("C");
  expect(new URL(fixture.base_url).hostname).toMatch(/^(localhost|127\.0\.0\.1)$/);
  expect(process.env.E2E_BASE_URL).toBe(fixture.base_url);
  const directory = join(fixture.evidence_dir, "ui-C"); mkdirSync(directory, { recursive: true });
  const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
  const beforeState = await page.request.get("/__f13/state"); expect(beforeState.ok()).toBe(true);
  const before = await beforeState.json();
  await page.goto("/app/");
  await page.getByLabel("Email").fill("123@example.com");
  await page.getByLabel("密碼").fill("123456");
  await page.getByRole("button", { name: "登入", exact: true }).click();
  await page.getByRole("link", { name: "F13 隔離驗收品牌", exact: true }).click();
  await page.getByRole("link", { name: "投放中心", exact: true }).click();
  await page.getByTestId("campaign-grid").getByText("F13 測試｜暫停活動", { exact: true }).first().click();
  const initialTasks = responseFor(page, "/material-tasks", "GET");
  await page.getByRole("button", { name: "素材", exact: true }).click();
  const taskListResponse = await initialTasks; expect(taskListResponse.ok()).toBe(true);
  const seeded = ((await taskListResponse.json()).tasks as Task[]).find(task => task.id === fixture.material_task_id);
  expect(seeded).toBeTruthy();
  await expect(page.getByRole("heading", { name: "準備這次需要的素材", exact: true })).toBeVisible();
  await capture(page, directory, "material-entry");

  // Existing finished media is usable without asking any model to regenerate it.
  await page.getByRole("button", { name: /^使用已有成品/ }).click();
  const editor = page.getByRole("region", { name: "素材任務", exact: true });
  const existingTitle = `瀏覽器已有成品 ${Date.now()}`;
  await editor.getByLabel("任務名稱", { exact: true }).fill(existingTitle);
  let response = responseFor(page, "/material-tasks");
  await editor.getByRole("button", { name: "保存素材需求", exact: true }).click();
  const existing = await taskResponse(response); expect(existing.mode).toBe("existing");
  await editor.getByRole("button", { name: "上傳或選擇成品", exact: true }).click();
  let dialog = page.getByRole("dialog", { name: "回收本批成品", exact: true });
  await chooseStored(dialog, "fixture-I1.png");
  response = responseFor(page, `/material-tasks/${existing.id}/candidates`);
  await dialog.getByRole("button", { name: "保存這批成品", exact: true }).click();
  const existingBatch = await taskResponse(response); expect(existingBatch.candidates).toHaveLength(1);
  await editor.getByRole("radio", { name: "成品 1", exact: true }).check();
  response = responseFor(page, `/material-tasks/${existing.id}/select`);
  await editor.getByRole("button", { name: "採用這份成品", exact: true }).click();
  const existingSelected = await taskResponse(response); expect(existingSelected.placement_id).toBeTruthy();
  await expect(editor.getByText("成品已加入素材安排，尚未上架平台", { exact: true })).toBeVisible();
  await capture(page, directory, "existing-adopted", ["fixture-I1.png"]);

  await page.getByRole("button", { name: "新增素材需求", exact: true }).click();
  await page.getByRole("button", { name: /^回收外部生圖/ }).click();
  const externalTitle = `瀏覽器 P2 回收 ${Date.now()}`;
  const p2 = "P2：以已保存的 R 合成色塊作為參考；這是隔離驗收素材，不是真實生成證明。";
  await editor.getByLabel("任務名稱", { exact: true }).fill(externalTitle);
  await editor.getByLabel("這次想傳達什麼", { exact: true }).fill("保留原廣告，另準備新素材供人工比較。");
  await editor.getByRole("textbox", { name: "素材提示詞", exact: true }).fill(p2);
  // I7 is already arranged as fixture B2. Explicitly retain its copy; adopting the same
  // original with conflicting copy must remain a product error, not silently overwrite it.
  await editor.getByRole("button", { name: /^搭配文案/ }).click();
  await editor.getByRole("textbox", { name: "素材標題", exact: true }).fill(seeded!.copy_fields.headline ?? "");
  await editor.getByRole("textbox", { name: "素材內文", exact: true }).fill(seeded!.copy_fields.body ?? "");
  await editor.getByRole("textbox", { name: "素材說明", exact: true }).fill(seeded!.copy_fields.description ?? "");
  await editor.getByRole("button", { name: "選擇或上傳參考圖", exact: true }).click();
  dialog = page.getByRole("dialog", { name: "選擇參考圖", exact: true });
  await chooseStored(dialog, "fixture-R.png");
  await dialog.getByRole("button", { name: "加入參考圖", exact: true }).click();
  await expect(editor.getByText("參考圖 R1", { exact: true }).first()).toBeVisible();
  response = responseFor(page, "/material-tasks");
  await editor.getByRole("button", { name: "保存素材需求", exact: true }).click();
  const external = await taskResponse(response);
  expect(external.prompt.text).toBe(p2);
  expect(external.reference_asset_ids).toEqual([fixture.reference_asset_id]);
  await capture(page, directory, "P2-reference-saved", ["參考圖 R1"]);
  await editor.getByRole("button", { name: "來源已保存，接著選擇成品", exact: true }).click();
  await editor.getByRole("button", { name: "上傳或選擇成品", exact: true }).click();
  dialog = page.getByRole("dialog", { name: "回收本批成品", exact: true });
  for (let index = 1; index <= 10; index++) await chooseStored(dialog, `fixture-I${index}.png`);
  await expect(dialog.getByText("已選 10 份原檔", { exact: true })).toBeVisible();
  response = responseFor(page, `/material-tasks/${external.id}/candidates`);
  await dialog.getByRole("button", { name: "保存這批成品", exact: true }).click();
  const gathered = await taskResponse(response); expect(gathered.candidates).toHaveLength(10);
  const seventh = gathered.candidates[6];
  expect(seventh.prompt.text).toBe(p2);
  expect(seventh.reference_asset_ids).toEqual([fixture.reference_asset_id]);
  await editor.getByRole("radio", { name: "成品 7", exact: true }).check();
  const candidateNames = gathered.candidates.map(candidate => candidate.filename);
  const selectedPreviews = await capture(page, directory, "ten-candidates-seventh-selected", candidateNames);
  response = responseFor(page, `/material-tasks/${external.id}/select`);
  await editor.getByRole("button", { name: "採用這份成品", exact: true }).click();
  const selected = await taskResponse(response);
  expect(selected.selected_candidate_id).toBe(seventh.id);
  expect(selected.placement_id).toBeTruthy();
  await page.reload();
  await expect(editor.getByRole("radio", { name: "成品 7", exact: true })).toBeChecked();
  await expect(editor.getByText("成品已加入素材安排，尚未上架平台", { exact: true })).toBeVisible();
  const reopenedPreviews = await capture(page, directory, "seventh-adopted-reopened", candidateNames);

  // Pick a different existing workbench copy version; do not dispatch another generation.
  await editor.getByRole("button", { name: "返回任務", exact: true }).click();
  const optionsResponse = responseFor(page, `/material-tasks/${fixture.next_material_task_id}/prompt-options`, "GET");
  await page.getByRole("button", { name: /^下一輪文案/ }).click();
  const optionsResult = await optionsResponse; expect(optionsResult.ok()).toBe(true);
  const options = (await optionsResult.json()).options as { part: string; label: string; version_id: string; copy_fields: { headline?: string; body?: string } }[];
  const copyOptions = options.filter(option => option.part === "copy"); expect(copyOptions.length).toBeGreaterThan(1);
  await editor.getByRole("button", { name: /^搭配文案/ }).click();
  const chosen = copyOptions[1];
  await editor.getByRole("button", { name: `使用${chosen.label}`, exact: true }).click();
  response = responseFor(page, `/material-tasks/${fixture.next_material_task_id}`, "PATCH");
  await editor.getByRole("button", { name: "保存本次修訂", exact: true }).click();
  const copied = await taskResponse(response);
  expect(copied.prompt.version_id).toBe(chosen.version_id);
  expect(copied.copy_fields).toEqual(chosen.copy_fields);
  await capture(page, directory, "workbench-copy-version-saved");
  await editor.getByRole("link", { name: "使用這版文案，修改原廣告", exact: true }).click();
  await expect(page.getByLabel("變更 1 新內文", { exact: true })).toHaveValue(copied.copy_fields.body ?? "");
  await page.getByLabel("清單名稱", { exact: true }).fill(`瀏覽器文案版本交接 ${Date.now()}`);
  const changesResponse = responseFor(page, "/change-sets");
  await page.getByRole("region", { name: "建立變更清單", exact: true }).getByRole("button", { name: "保存清單，檢視並核准", exact: true }).click();
  const change = await changesResponse; expect(change.ok(), await change.text()).toBe(true);
  expect(change.request().postDataJSON()).toMatchObject({ material_task_id: copied.id, material_revision: copied.revision });
  const changeSet = (await change.json()).change_set;
  await page.reload();
  await expect(page.getByRole("button", { name: "核准這份變更清單", exact: true })).toBeVisible();
  await capture(page, directory, "copy-change-draft-reopened");
  const afterResponse = await page.request.get("/__f13/state"); expect(afterResponse.ok()).toBe(true);
  const after = await afterResponse.json();
  expect(after.provider_calls).toBe(before.provider_calls);
  expect(after.blocked_external).toBe(before.blocked_external);
  expect(errors).toEqual([]);
  writeFileSync(join(directory, "ui-receipt.json"), JSON.stringify({
    phase: "C", existing_task: existingSelected.id, existing_placement: existingSelected.placement_id,
    external_task: selected.id, prompt: p2, reference_asset_id: fixture.reference_asset_id,
    chosen_ui_position: 7, chosen_candidate: seventh, placement_id: selected.placement_id,
    selected_previews: selectedPreviews, reopened_previews: reopenedPreviews,
    copy_task: copied.id, copy_revision: copied.revision, copy_version_id: chosen.version_id,
    change_set_id: changeSet.id, provider_calls_before: before.provider_calls, provider_calls_after: after.provider_calls,
    page_errors: errors, capability: "Isolated fixture HTTP and UI only; no real AI or platform writes.",
  }, null, 2));
});
