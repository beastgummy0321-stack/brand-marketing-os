/** 素材工作檯 API 型別與呼叫（票 15-workbench-entry）。
 * 對應 app/ads/routes_workbench.py，掛在 /api/ads 前綴下。回應是裸 JSON
 * （不是駕駛艙模組 lib/api.ts 用的 {data, generated_at} 信封）；失敗回
 * {"error": "訊息"} ＋非 2xx 狀態碼（見 app/ads 底下其他路由的既有慣例）。 */

/** 工作檯任務卡（畫面1）：目前唯一來源是「廣告檔期」——計畫已核准且矩陣還沒生完的檔期
 * 各出一張（app/ads/routes_workbench.py workbench_tasks()）。檔期沒有名稱欄位，
 * `cycle_label` 是後端組好的日期範圍字串，前端直接顯示、不必自己拼。 */
export interface WorkbenchTask {
  source: string;
  cycle_id: string;
  cycle_label: string;
  generated_cells: number;
  total_cells: number;
  adopted_count: number;
}

export async function fetchWorkbenchTasks(brandId: string): Promise<WorkbenchTask[]> {
  const res = await fetch(`/api/ads/brands/${encodeURIComponent(brandId)}/workbench/tasks`);
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res, "工作檯任務讀取失敗"));
  }
  const body: { tasks: WorkbenchTask[] } = await res.json();
  return body.tasks;
}

/** 矩陣頁（畫面2，票 16-matrix-page）：格子三態之一，對應
 * app/ads/routes_creative_theme.py theme_matrix()。`generating` 恆不會從後端回來
 * （見該路由註解），是前端點下「生成一個主題」後自己疊上的樂觀進行中態，不是伺服器狀態，
 * 故這裡的型別只收 empty／themed 兩種，generating 由 MatrixPage 自己的畫面狀態表達。 */
export interface MatrixTheme {
  id: string;
  name: string;
  /** "draft" | "adopted"，比照 app/ads/theme_repository.py 寫入的字面值。 */
  status: string;
}

export interface MatrixFormatEmpty {
  state: "empty";
  /** 美元，pricing.cost_ceiling() 天花板估計，見後端路由註解。 */
  estimated_cost: number;
}

export interface MatrixFormatThemed {
  state: "themed";
  themes: MatrixTheme[];
}

export type MatrixFormatCell = MatrixFormatEmpty | MatrixFormatThemed;

export interface MatrixCellRow {
  experiment_cell_id: string;
  creative_angle: string;
  /** key＝格式（single_image／carousel／video）。 */
  formats: Record<string, MatrixFormatCell>;
}

/** `angleLocked`（票 04-angle-rename 決議）：這期交接包已產出時 true，矩陣頁列首的改名
 * 鉛筆要隱藏——判準是 `app/ads/handoff.py has_publishing_package()`，跟改名路由本身同一顆。 */
export async function fetchMatrix(
  brandId: string,
  cycleId: string,
): Promise<{ cells: MatrixCellRow[]; angleLocked: boolean }> {
  const res = await fetch(
    `/api/ads/brands/${encodeURIComponent(brandId)}/ads/${encodeURIComponent(cycleId)}/matrix`,
  );
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res, "矩陣資料讀取失敗"));
  }
  const body: { cells: MatrixCellRow[]; angle_locked: boolean } = await res.json();
  return { cells: body.cells, angleLocked: body.angle_locked };
}

/** 切角名稱輸入框上限，對照 `app/ads/plan.py MAX_ANGLE_LENGTH`。 */
export const MAX_ANGLE_LENGTH = 30;

/** 切角改名（票 04-angle-rename 決議）：對應 `app/ads/routes_campaigns_open_api.py
 * rename_cell_angle()`，網址是 `/api/campaigns/...` 不是本檔其餘路由的 `/api/ads/...`——
 * cell 掛在檔期底下，改名路由跟企劃提案書（`warroomApi.ts`）共用同一支，不是矩陣頁專屬。
 * 空白／超長／已產交接包三種都是 400，錯誤訊息走 `extractErrorMessage`。 */
export async function renameAngle(
  brandId: string,
  cycleId: string,
  cellId: string,
  creativeAngle: string,
): Promise<string> {
  const res = await fetch(
    `/api/campaigns/${encodeURIComponent(brandId)}/${encodeURIComponent(cycleId)}` +
      `/cells/${encodeURIComponent(cellId)}/angle`,
    {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ creative_angle: creativeAngle }),
    },
  );
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res, "改名失敗"));
  }
  const body: { ok: boolean; creative_angle: string } = await res.json();
  return body.creative_angle;
}

/** 灰卡「生成一個主題」：打 app/ads/routes_creative_theme.py generate_theme()。成功回整包
 * 主題（含全部元件），矩陣格只需要 id／name／status 這三項光摘要，其餘欄位呼叫端不取用。 */
export async function generateTheme(
  brandId: string,
  cycleId: string,
  cellId: string,
  formatKey: string,
): Promise<MatrixTheme> {
  const res = await fetch(
    `/api/ads/brands/${encodeURIComponent(brandId)}/ads/${encodeURIComponent(cycleId)}` +
      `/cells/${encodeURIComponent(cellId)}/formats/${encodeURIComponent(formatKey)}/themes`,
    { method: "POST" },
  );
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res, "生成失敗"));
  }
  const body: { theme: MatrixTheme } = await res.json();
  return body.theme;
}

/** 非 2xx 回應優先讀 `{"error": "..."}`；讀不到（例如品牌不存在時走全站 404 錯誤頁，
 * body 是 HTML 不是 JSON）就退回帶狀態碼的通用訊息。`detail` 是 FastAPI 內建
 * `HTTPException`／`NotFoundKind` 的欄位名（票 04-angle-rename 改名路由用這個，跟本檔
 * 其餘手動 `JSONResponse({"error": ...})` 路由不同源），兩種都讀。 */
async function extractErrorMessage(res: Response, fallbackAction: string): Promise<string> {
  try {
    const body: { error?: string; detail?: string } = await res.json();
    if (body.error) return body.error;
    if (body.detail) return body.detail;
  } catch {
    // 不是 JSON，用預設訊息。
  }
  return `${fallbackAction}（狀態碼 ${res.status}）`;
}

// ---------------------------------------------------------------------------
// 側板（畫面3，票 17-panel-single-image）：單一主題完整內容、採用、退件、複製、開資料夾。
// ---------------------------------------------------------------------------

/** 生成當下即掃的法務／品牌命中（票 S1-01：scan-on-generate），對應
 * `app/ads/compliance.py scan_components()` 的 hit 形狀。`category` 三選一——
 * `"law"`＝內建法定紅線詞、`"unbacked_claim"`＝查無佐證的規格／交易條件都算紅色；
 * `"brand"`＝這個品牌自己的宣稱／規則命中，算黃色（跟既有 `similarity_flag` 徽章同一組
 * warning token）。`message` 是完整人話句子，`term` 是徽章上顯示的短字。 */
export interface ComplianceHit {
  category: "law" | "brand" | "unbacked_claim";
  severity: "warn" | "info";
  term: string;
  message: string;
}

/** 主題元件（app/ads/theme_repository.py list_theme_components() 回應形狀）。`over_budget`／
 * `similarity_flag` 在 sqlite 裡是 INTEGER（0／1），FastAPI 原樣序列化，不是 JS boolean——
 * 呼叫端要用 `!!` 轉，不能直接當 boolean 用（見 app/tests/test_ads_theme_detail.py 斷言）。
 * `rejected` 是路由層另外算好的真 Python bool，序列化後才是 JSON true／false。
 * `compliance_hits`（票 S1-01）：`adopt_theme()`／`reject_theme_component()` 兩支路由沒有
 * 重新掃描，回傳的元件不帶這個欄位——呼叫端不能假設它一定存在，見 ComplianceBadges.tsx。 */
export interface ThemeComponentData {
  id: string;
  component_type: string;
  content: string;
  sequence: number | null;
  over_budget: number;
  similarity_flag: number;
  rejected: boolean;
  reject_reason_label: string | null;
  compliance_hits?: ComplianceHit[];
}

/** `scan_note`（票 S1-01）：跟 `compliance_hits` 同一個限制——只有 `fetchThemeDetail()` 真的
 * 從後端 `scan_note` 欄位補上，`adoptTheme()` 的回應沒有這個欄位，補不出來，維持 undefined。 */
export interface ThemeDetail {
  id: string;
  name: string;
  status: string;
  format_key: string;
  components: ThemeComponentData[];
  scan_note?: string;
}

/** 側板開啟時抓完整內容：對應 app/ads/routes_creative_theme.py get_theme_detail()（票 17
 * 新增，補矩陣資料端點只回摘要的缺口，見該路由註解）。 */
export async function fetchThemeDetail(
  brandId: string,
  cycleId: string,
  themeId: string,
): Promise<ThemeDetail> {
  const res = await fetch(
    `/api/ads/brands/${encodeURIComponent(brandId)}/ads/${encodeURIComponent(cycleId)}` +
      `/themes/${encodeURIComponent(themeId)}`,
  );
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res, "主題內容讀取失敗"));
  }
  // scan_note 是回應的頂層欄位，跟 theme 平行（不是 theme 底下的鍵），這裡補回
  // ThemeDetail 物件上（票 S1-01）。
  const body: { theme: ThemeDetail; scan_note: string } = await res.json();
  return { ...body.theme, scan_note: body.scan_note };
}

/** 「採用整個主題」主 CTA：對應 app/ads/routes_creative_theme.py adopt_theme()。 */
export async function adoptTheme(
  brandId: string,
  cycleId: string,
  themeId: string,
): Promise<ThemeDetail> {
  const res = await fetch(
    `/api/ads/brands/${encodeURIComponent(brandId)}/ads/${encodeURIComponent(cycleId)}` +
      `/themes/${encodeURIComponent(themeId)}/adopt`,
    { method: "POST" },
  );
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res, "採用失敗"));
  }
  const body: { theme: ThemeDetail } = await res.json();
  return body.theme;
}

/** 單一元件退件＋理由：對應 app/ads/routes_creative_theme.py reject_theme_component()。 */
export async function rejectComponent(
  brandId: string,
  cycleId: string,
  componentId: string,
  reasonCode: string,
): Promise<ThemeComponentData> {
  const res = await fetch(
    `/api/ads/brands/${encodeURIComponent(brandId)}/ads/${encodeURIComponent(cycleId)}` +
      `/components/${encodeURIComponent(componentId)}/reject`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ reason_code: reasonCode }),
    },
  );
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res, "退件失敗"));
  }
  const body: { component: ThemeComponentData } = await res.json();
  return body.component;
}

/** 整組複製圖片提示詞：對應 app/ads/routes_creative_theme.py copy_theme_image_prompts()。
 * 一組上限 10 則，超過拆多組（ADR 0008 三），呼叫端自行決定怎麼拼多組內容。 */
export async function fetchImagePromptsCopy(
  brandId: string,
  cycleId: string,
  themeId: string,
): Promise<{ content: string; count: number }[]> {
  const res = await fetch(
    `/api/ads/brands/${encodeURIComponent(brandId)}/ads/${encodeURIComponent(cycleId)}` +
      `/themes/${encodeURIComponent(themeId)}/image-prompts/copy`,
  );
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res, "複製內容取得失敗"));
  }
  const body: { groups: { content: string; count: number }[] } = await res.json();
  return body.groups;
}

/** 這期檔期素材資料夾的大小：對應 app/ads/routes_creative_theme.py cycle_folder()。
 * `exists: false`＝資料夾還沒建立（`size_label` 為 null），跟「建立了但還是空的」
 * （`"0.0 MB"`）是兩件事，後端刻意分開，前端不得混成同一句話。 */
export interface CycleFolder {
  exists: boolean;
  size_label: string | null;
}

export async function fetchCycleFolder(brandId: string, cycleId: string): Promise<CycleFolder> {
  const res = await fetch(
    `/api/ads/brands/${encodeURIComponent(brandId)}/ads/${encodeURIComponent(cycleId)}/folder`,
  );
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res, "資料夾狀態讀取失敗"));
  }
  return (await res.json()) as CycleFolder;
}

/** 開這期檔期的素材資料夾（沒有就建）：對應 open_cycle_folder()，跟主題層同一支
 * creative_assets.open_folder()，只差不傳主題資料夾名。 */
export async function openCycleFolder(brandId: string, cycleId: string): Promise<string> {
  const res = await fetch(
    `/api/ads/brands/${encodeURIComponent(brandId)}/ads/${encodeURIComponent(cycleId)}/folder`,
    { method: "POST" },
  );
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res, "開資料夾失敗"));
  }
  const body: { folder_path: string } = await res.json();
  return body.folder_path;
}

/** 開這個主題的素材資料夾：對應 app/ads/routes_creative_theme.py open_theme_folder()
 * （伺服器端 os.startfile，單機單人使用，決策 0008）。 */
export async function openThemeFolder(
  brandId: string,
  cycleId: string,
  themeId: string,
): Promise<string> {
  const res = await fetch(
    `/api/ads/brands/${encodeURIComponent(brandId)}/ads/${encodeURIComponent(cycleId)}` +
      `/themes/${encodeURIComponent(themeId)}/folder`,
    { method: "POST" },
  );
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res, "開資料夾失敗"));
  }
  const body: { folder_path: string } = await res.json();
  return body.folder_path;
}

/** 退件理由清單：沒有列舉端點（app/ads 底下查過，/api/ads 只有拿理由碼當輸入的 reject
 * 路由，沒有回傳清單的 GET），照抄後端常數定義 app/ads/fingerprint.py:71-81
 * REJECT_REASONS（查證日 2026-08-09）。這份清單「從沒變過」（code-rules 第二節）——
 * 兩邊要是哪天真的不同步，reject 路由的 400（`reason_code not in REJECT_REASON_LABELS`）
 * 會立刻炸，不會悄悄壞掉。 */
export const REJECT_REASONS: [code: string, label: string][] = [
  ["too_stiff", "太生硬，不像真人講話"],
  ["off_brand", "不是我們品牌的調性"],
  ["too_ad_like", "太像廣告，人會直接滑掉"],
  ["too_similar", "跟其他張太像"],
  ["discount_too_deep", "折扣或促銷講得太重"],
  ["overclaim", "講得太滿，有風險"],
  ["wrong_product", "產品資訊不對"],
  ["visual_weird", "畫面感覺怪"],
  ["hook_weak", "開頭抓不住人"],
];

/** 單圖格式的文字元件字數預算：沒有 API 回傳這個數字（元件只帶 `over_budget` 布林），
 * 照抄後端常數定義 app/creative/format_specs.py FORMAT_SPECS.single_image.fields
 * （查證日 2026-08-09）。只收本票範圍內的三種文字型別，image_prompt 沒有字數預算
 * （`char_budget: None`），不進這張表。 */
export const SINGLE_IMAGE_CHAR_BUDGETS: Record<string, number> = {
  body: 125,
  title: 27,
  description: 30,
};

// ---------------------------------------------------------------------------
// 側板（畫面4，票 18-panel-carousel）：輪播主題內容——敘事骨架標記＋有序卡片＋廣告層文案。
// 沿用票 17 的 fetchThemeDetail／adoptTheme／rejectComponent／ThemeComponentData，本節只補
// 輪播特有的兩張抄錄表，不另開一組 API 呼叫。
// ---------------------------------------------------------------------------

/** 輪播格式的文字元件字數預算：同單圖規則，照抄 app/creative/format_specs.py
 * FORMAT_SPECS.carousel.fields（查證日 2026-08-09）。`card_image_prompt`／
 * `card_product_link` 沒有字數預算，不進這張表；`body` 是廣告層文案，跟單圖的 body 預算
 * （125）不同，輪播是 80，不能共用 SINGLE_IMAGE_CHAR_BUDGETS。 */
export const CAROUSEL_CHAR_BUDGETS: Record<string, number> = {
  card_title: 45,
  card_description: 20,
  body: 80,
};

/** 敘事骨架人話標籤：照抄 app/creative/format_specs.py FORMAT_SPECS.carousel.narrative_types
 * 的鍵（查證日 2026-08-09），只取分類短名，冒號後的說明句側板空間放不下、也不必要
 * （契約條文「側板只標示，不給使用者改骨架」）。 */
export const NARRATIVE_TYPE_LABELS: Record<string, string> = {
  steps: "步驟型",
  before_after: "對比型",
  multi_product: "多商品型",
};

// ---------------------------------------------------------------------------
// 側板（畫面5，票 19-panel-video）：影片腳本主題內容——腳本×Hook 組合＋廣告層文案。
// 沿用票 17 的 fetchThemeDetail／adoptTheme／rejectComponent／ThemeComponentData，本節只補
// 影片格式特有的腳本解析與字數預算表，不另開一組 API 呼叫。
// ---------------------------------------------------------------------------

/** 影片格式的文字元件字數預算：body/title/description 數字剛好跟單圖同一組，但獨立照抄
 * app/creative/format_specs.py FORMAT_SPECS.video.fields 開一份（查證日 2026-08-09）——
 * 跟票 18 CAROUSEL_CHAR_BUDGETS 同一個理由：每個格式各自對規格表抄一份，不靠「數字剛好
 * 相同」互相借用，規格表哪天分家不用回頭改到別的格式。script／hook_pool 沒有字數預算，
 * 不進這張表。 */
export const VIDEO_CHAR_BUDGETS: Record<string, number> = {
  body: 125,
  title: 27,
  description: 30,
};

/** script 元件 content 的形狀：`app/creative/theme_engine_video.py normalize_video()` 寫入
 * 前用 `json.dumps({"framework": ..., "segments": [...]})`（查證日 2026-08-09，見該檔
 * component_type=="script" 那段與 app/tests/test_video_theme.py 對應斷言）。第一段
 * （Hook 段）的 dialogue 固定是後端插槽佔位字串，這裡不特別處理——腳本清單只顯示
 * label 串成的段落摘要，不顯示 dialogue。 */
export interface VideoScriptSegment {
  label: string;
  dialogue: string;
  visual: string;
}

export interface VideoScript {
  framework: string;
  segments: VideoScriptSegment[];
}

/** 壞掉的 JSON 或形狀不對（理論上不會，後端寫入前已驗證過）回 null，呼叫端自行決定
 * 怎麼顯示，不整頁炸掉。 */
export function parseVideoScript(content: string): VideoScript | null {
  try {
    const data = JSON.parse(content) as Partial<VideoScript>;
    if (typeof data.framework === "string" && Array.isArray(data.segments)) {
      return data as VideoScript;
    }
  } catch {
    // 不是合法 JSON，當作解析失敗處理。
  }
  return null;
}

// ---------------------------------------------------------------------------
// 快速生成（畫面1 下半，契約 G12）：不開檔期、不落地，端點回應即棄。掛在 /api/creative
// 前綴下（app/ads/routes_quick_generate.py），不是 /api/ads。
// ---------------------------------------------------------------------------

/** 快速生成的四種類型，字面值＝後端 `QUICK_GENERATE_SCOPES` 的鍵
 * （app/creative/format_specs.py:104，查證日 2026-08-11）。 */
export type QuickGenerateScope = "post" | "video" | "image" | "script";

/** 快速生成回傳的元件：**跟側板的 `ThemeComponentData` 不是同一個形狀**——不落地代表沒有
 * DB 主鍵（沒有 `id`）、沒有退件與相似度旗標，`sequence` 只有 hook_pool 帶
 * （app/creative/theme_engine_video.py:200）。因此側板的 ComponentSection／ComponentRow
 * 不能重用在這裡（那兩顆一定要 `component.id` 才能打退件端點）。 */
export interface QuickGenerateComponent {
  component_type: string;
  content: string;
  /** 票 S1-01：跟側板不同，快速生成只有這一條路徑會回應，後端保證每則元件都帶（乾淨的是
   * 空陣列，不是缺席鍵），不必比照 `ThemeComponentData.compliance_hits` 標成可選。 */
  compliance_hits: ComplianceHit[];
}

export interface QuickGenerateResult {
  scope: QuickGenerateScope;
  name: string;
  components: QuickGenerateComponent[];
  /** 票 S1-01：`quick_generate()` 一律附上，跟 `ThemeDetail.scan_note` 不同，不必標可選。 */
  scan_note: string;
}

export interface QuickGenerateProduct {
  id: string;
  name: string;
}

/** 產品 pills 的清單：對應 app/ads/routes_quick_generate.py quick_generate_products()。 */
export async function fetchQuickGenerateProducts(
  brandId: string,
): Promise<QuickGenerateProduct[]> {
  const res = await fetch(`/api/creative/brands/${encodeURIComponent(brandId)}/products`);
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res, "產品清單讀取失敗"));
  }
  const body: { products: QuickGenerateProduct[] } = await res.json();
  return body.products;
}

/** 快速生成本體：對應 quick_generate()。`productId` 傳 null＝不指定產品（純品牌範圍）。
 * 失敗一律走既有 `{"error": "人話訊息"}` 慣例（契約 G12.8）。 */
export async function quickGenerate(
  brandId: string,
  scope: QuickGenerateScope,
  topic: string,
  productId: string | null,
): Promise<QuickGenerateResult> {
  const res = await fetch(
    `/api/creative/brands/${encodeURIComponent(brandId)}/quick-generate`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ scope, topic, product_id: productId }),
    },
  );
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res, "生成失敗"));
  }
  // scan_note 是回應的頂層欄位，跟 result 平行，這裡補回 QuickGenerateResult 物件上
  // （票 S1-01，同 fetchThemeDetail() 的作法）。
  const body: { result: QuickGenerateResult; scan_note: string } = await res.json();
  return { ...body.result, scan_note: body.scan_note };
}

/** 腳本×Hook 組合成完整文字：對應 app/ads/routes_creative_theme.py
 * combine_video_script_route()（票 23）。Hook 已套入插槽，前端不重算組字邏輯，純轉發後端
 * 組好的內容。 */
export async function combineVideoScript(
  brandId: string,
  cycleId: string,
  themeId: string,
  hookComponentId: string,
): Promise<string> {
  const res = await fetch(
    `/api/ads/brands/${encodeURIComponent(brandId)}/ads/${encodeURIComponent(cycleId)}` +
      `/themes/${encodeURIComponent(themeId)}/combine-script`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ hook_component_id: hookComponentId }),
    },
  );
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res, "腳本組合失敗"));
  }
  const body: { script: string } = await res.json();
  return body.script;
}
