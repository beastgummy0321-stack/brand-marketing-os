import { expect, test } from "@playwright/test";

/** 全站煙霧測試（票 shell-04，HANDOFF-shell-slice.md §4）。
 *
 * 一條路徑走完活下來的主要畫面：註冊登入 → 跨品牌總覽 → 建檔精靈建一個品牌 →
 * 品牌頁 → 產品 → 訂單。這支證明的是「切掉 `app/ads/` 之後畫面還走得通」，
 * 不逐頁斷言內容——畫面內容的細節不歸它管（工作流規範：畫面行為只給一支
 * 端到端煙霧測試，不寫單元測試）。
 *
 * 它取代了 `app/tests/test_architecture_boundaries.py` 裡兩支昂貴又脆的掃描
 * （`ClipboardHonestyScanTest`／`ReviewStepSettleRefetchWiringTest`）——那兩支
 * 斷言的都是畫面行為，存在的唯一原因是這個專案沒有煙霧測試。
 *
 * 不花錢：品牌只填名稱、描述與網址留空，一樣進精靈，但沒東西可掃所以
 * `app/intake/state.start_draft()` 直接把草稿停在第 3 步、不呼叫 AI。
 * 改動這支時務必維持這個性質。
 */
test("走完切片後活下來的主要畫面", async ({ page }) => {
  // 每次跑用一個新帳號：本機 Supabase 關掉了信箱驗證（supabase/config.toml
  // `enable_confirmations = false`），註冊完當場就有 session，不必收信。
  const stamp = Date.now();
  const email = `smoke-${stamp}@example.com`;
  const password = `smoke-pw-${stamp}`;
  const brandName = `虛構煙霧測試品牌 ${stamp}`;

  // --- 註冊並登入 -----------------------------------------------------------
  await page.goto("/app/login");
  await page.getByRole("button", { name: "還沒有帳號？註冊新帳號" }).click();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("密碼").fill(password);
  await page.getByRole("button", { name: "註冊", exact: true }).click();

  // --- 跨品牌總覽 -----------------------------------------------------------
  await expect(page.getByRole("link", { name: "新增品牌" }).first()).toBeVisible();

  // --- 建檔精靈：只填品牌名稱，走不花錢的陽春路徑 ---------------------------
  await page.getByRole("link", { name: "新增品牌" }).first().click();
  await expect(page.getByRole("heading", { name: "建立品牌", exact: true })).toBeVisible();
  await page.getByLabel("品牌名稱", { exact: true }).fill(brandName);

  // --- 投放史二選一（F05-I06）：做在步驟一表單裡，沒選不能往下；這裡選「完全沒投過」，
  // 陽春路徑不牽涉背景補拉。沒給網站和照片，按鈕是「下一步」不是「讓系統讀網站」。-----------
  await page.getByRole("radio", { name: "完全沒投過" }).check();
  await page.getByRole("button", { name: "下一步 →" }).click();

  // --- 沒東西可掃：略過第 2 步（AI 讀網站），草稿直接停在第 3 步「品牌是誰」（F42-I06）------
  await expect(page).toHaveURL(/\/app\/brands\/brd_.+\/intake/);
  await expect(page.getByRole("heading", { name: "品牌是誰", exact: true })).toBeVisible();

  const brandId = new URL(page.url()).pathname.split("/")[3];

  // --- 品牌頁：外殼切片後是品牌標題，右上角是進投放中心的入口（缺陷 3）-------------
  await page.goto(`/app/brands/${brandId}`);
  await expect(page.getByRole("heading", { name: "經營概況", exact: true })).toBeVisible();
  await expect(page.getByText(brandName, {exact:true}).first()).toBeVisible();
  await expect(page.getByRole("link", { name: "前往投放中心" })).toBeVisible();

  // --- 投放中心：缺陷 3 —— 品牌頁要有真的入口，不是只能手打網址 -------------------
  // F28-I08 起首頁是 v9 board D，h1 是「N 月的廣告」——「投放中心」只在外殼麵包屑，
  // 不是頁面 heading（design-system.md §5.1）。
  await page.getByRole("link", { name: "前往投放中心" }).click();
  await expect(page).toHaveURL(new RegExp(`/app/brands/${brandId}/ads$`));
  await expect(page.getByRole("heading", { level: 1, name: /^\d{1,2} 月的廣告$/ })).toBeVisible();

  // --- 素材工作檯（F02 大重置，ARCHITECTURE.md §5.1-§5.3）：入口 → 自由創作 → 任務包頁 →
  // 素材組 studio 的完整走查（F02-I11）。跑在沒有 worker、沒有 provider key 的 e2e 後端上
  // （F02 Decisions「e2e asserts only what runs with no worker and no provider key」）——
  // 現在是 BRAND_OS_LLM_PROVIDER=scripted、BRAND_OS_JOB_QUEUE=memory（F06-I05）：
  // 「AI 解析結果」由罐頭回覆回答 workbench_free_parse（parsed: true，一則 image_prompt），
  // 但它的生成 job 從沒被排進佇列、永遠不會跑，所以圖片 tab 仍停在「還沒有生成過」的空狀態。
  // ------------------------------------------------------------------------------------
  await page.goto(`/app/brands/${brandId}/workbench`);
  await expect(page.getByRole("heading", { name: "素材工作檯", exact: true })).toBeVisible();
  await expect(page.getByText("目前沒有任務包")).toBeVisible();

  await page.getByRole("button", { name: "＋ 自由創作" }).first().click();
  await expect(page).toHaveURL(new RegExp(`/app/brands/${brandId}/workbench/new$`));

  // 精準控制：選 圖片 當素材類型，讓建出來的任務包要求 `image_prompt`。
  await page.getByRole("button", { name: "精準控制" }).click();
  await page.getByLabel("素材類型").selectOption("image_prompt");
  await page.getByLabel("告訴 AI 你想創作什麼").fill("幫這個品牌做一張活動宣傳圖");

  // 第一次點擊：真的打一次 `/parse`；e2e 後端回罐頭回覆（workbench_free_parse，parsed:
  // true），但「精準控制」已經明講素材類型是 image_prompt，畫面照樣往下走。
  await page.getByRole("button", { name: "建立自由工作" }).click();
  await expect(page.getByRole("button", { name: "確認並生成" })).toBeVisible();
  await expect(page.getByText("需要產出")).toBeVisible();

  // 第二次點擊：`POST /packs`，落地到剛建立的任務包頁。
  await page.getByRole("button", { name: "確認並生成" }).click();
  await expect(page).toHaveURL(new RegExp(`/app/brands/${brandId}/workbench/packs/[^/]+$`));

  await expect(page.getByText("任務包", { exact: true })).toBeVisible();
  await expect(page.getByText("總覽", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "完成進度" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "素材組進度" })).toBeVisible();

  // API 自己出的字：`未生成`（`cells[].text`）——`frontend/src` 底下沒有這個字面，出現在
  // 畫面上只可能是後端給的（F02 Decisions）。剛建的任務包還沒生成過，所以圖片欄是這個字。
  await expect(page.getByRole("cell", { name: "未生成", exact: true })).toBeVisible();

  // 打開這個素材組的 studio。
  await page.getByRole("cell", { name: "未生成", exact: true }).locator("..").click();
  await expect(page).toHaveURL(
    new RegExp(`/app/brands/${brandId}/workbench/packs/[^/]+/sets/[^/]+$`),
  );
  await expect(page.getByRole("tab", { name: "圖片" })).toBeVisible();
  // Memory queue deliberately does not run workers: queued work must not look empty.
  await expect(page.getByText("素材已排隊，等待生成。")).toBeVisible();
  await expect(page.getByRole("button", { name: "生成中…" })).toBeDisabled();
  await expect(page.getByText("還沒有生成過")).toHaveCount(0);

  // --- 商品（F43-I07）-------------------------------------------------------
  await page.goto(`/app/brands/${brandId}/products`);
  await expect(page.getByRole("heading", { name: "商品", exact: true, level: 1 })).toBeVisible();

  // --- 訂單 -----------------------------------------------------------------
  await page.goto(`/app/brands/${brandId}/orders`);
  await expect(page.getByRole("heading", { name: "訂單與顧客" })).toBeVisible();

  // --- 品牌智庫：上傳一張圖，而且那張圖真的畫得出來 --------------------------
  // 第 ⑥ 片（2026-08-30）加。上傳走的是真的 Supabase Storage（ADR 0043），所以這一段
  // 順便證明「存得進去、讀得回來」；但它真正守的是**縮圖有沒有真的顯示**——
  // `naturalWidth > 0` 才算數，`toBeVisible()` 不算：破圖的 <img> 也是可見的。
  // 這條路以前沒有任何測試走過，於是「圖片路由要求登入、<img> 不會帶權杖」這個 401
  // 在畫面上安靜地退化成一個小圖示，撐到 2026-08-30 手動驗收才被抓到。
  await page.goto(`/app/brands/${brandId}/library`);
  await page.getByRole("button", { name: "官方素材" }).click();
  await page.getByRole("button", { name: "上傳素材" }).click();
  await page.locator('input[type="file"]').setInputFiles({
    name: "smoke.png",
    mimeType: "image/png",
    // 1x1 紅點 PNG：夠小、是合法的 PNG，瀏覽器解得開才會有 naturalWidth。
    buffer: Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
      "base64",
    ),
  });
  await page.getByLabel("種類").selectOption("logo");
  await page.getByRole("button", { name: "上傳這個素材" }).click();

  const thumbnail = page.locator('img[alt="Logo"]').first();
  await expect(thumbnail).toBeVisible();
  await expect
    .poll(() => thumbnail.evaluate((img) => (img as HTMLImageElement).naturalWidth))
    .toBeGreaterThan(0);

  // --- 把過去的廣告帶進來（票 past-ads/04，ADR 0067）：e2e 帳號沒有 Meta 權杖，這裡只
  // 證明畫面到得了、空狀態文案對——真的拉 Meta 資料歸驗收，不歸這支煙霧測試 -----------
  await page.goto(`/app/brands/${brandId}/intake/history`);
  await expect(page.getByText("還沒接上 Meta 廣告帳戶")).toBeVisible();

  // --- 未知網址落在殼層裡的 404，不是空白頁（票 workbench-2/03，
  // issue-unknown-url-renders-a-blank-page）--------------------------------------------
  await page.goto(`/app/brands/${brandId}/nothing`);
  await expect(page.getByRole("heading", { name: "找不到這一頁" })).toBeVisible();
  await page.getByRole("link", { name: "回品牌總覽" }).click();
  await expect(page.getByRole("heading", { name: "品牌總覽" })).toBeVisible();
});
