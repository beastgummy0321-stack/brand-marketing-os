/** 假資料源（票 B3-intake，畫面契約第 1 段）。跟其他 feature 的假資料源各自獨立、各自可
 * 整包刪除。初掃印象／問答題庫／交接包腳本／貼回樣本逐字移植 `app/intake/script.py`
 * （查證日 2026-08-12）——Mock 階段本來就不論使用者填了什麼，內容都是同一份預寫腳本
 * （script.py 檔頭原話），這裡照抄同一個設計，不用為了「看起來動態」另外生成內容。 */
import type {
  CostItem,
  CurrentQuestion,
  IntakeDraft,
  IntakeJobKind,
  IntakeJobState,
  IntakeReviewItem,
  ScanImpression,
  UrlResult,
} from "@/lib/intakeApi";
import { COST_PASTE_FIX, COST_QUESTION, COST_SCAN, DEFAULT_BUDGET } from "@/lib/intakeApi";

let idCounter = 0;
export function nextId(prefix: string): string {
  idCounter += 1;
  return `${prefix}-${idCounter}`;
}

// ---------------------------------------------------------------------------
// 初掃：5 條印象（script.py SCAN_IMPRESSIONS）
// ---------------------------------------------------------------------------

export const SCAN_IMPRESSIONS: ScanImpression[] = [
  {
    looks_like: "產品線",
    title: "四款茶、以烏龍為主",
    content: "網站商品頁看得到四款，三款烏龍一款紅茶，每款都標產區與製茶師姓名。",
    basis: "官網商品頁",
  },
  {
    looks_like: "價格帶",
    title: "中高價位",
    content: "單包 150 元上下、禮盒 880 元起，比同通路的量販茶包高約四成。",
    basis: "官網商品頁",
  },
  {
    looks_like: "受眾",
    title: "偏送禮與自用兼具",
    content: "禮盒佔商品數一半，文案多次提到「送長輩」「回禮」，自用包裝相對少。",
    basis: "官網、粉專近期貼文",
  },
  {
    looks_like: "語調",
    title: "溫和、少驚嘆號",
    content: "粉專近 20 篇貼文幾乎沒有促銷語氣，多是產地與製程紀錄。",
    basis: "粉專近期貼文",
  },
  {
    looks_like: "法規風險",
    title: "有一句可能踩線",
    content: "商品頁出現「幫助代謝」字樣，這在食品廣告可能需要佐證，要客戶確認來源。",
    basis: "官網商品頁",
  },
];

export const MOCK_PRODUCT_NAME = "烏龍茶包";
export const SCAN_DETECTED_PRODUCTS = [MOCK_PRODUCT_NAME, "紅茶禮盒"];

// ---------------------------------------------------------------------------
// 引導問答：5 題（script.py QUESTIONS），最多 8 題
// ---------------------------------------------------------------------------

export const MAX_QUESTIONS = 8;

export const QUESTIONS: CurrentQuestion[] = [
  {
    question: "這個品牌最想被記住的是什麼？",
    suggested: {
      label: "單一產區的可追溯性",
      desc: "我從官網看到你們每款茶都標產區與製茶師，這在同價位帶不常見，適合當主要記憶點。選這個，調研會往「產地故事怎麼講」的方向去。",
    },
    branches: [
      { label: "冷泡也不苦的口感", desc: "偏產品體驗。選這個，調研會往「口感怎麼描述才不踩食品廣告的線」去。" },
      { label: "送禮場合的體面感", desc: "偏使用情境。選這個，調研會往「禮盒定位與競品比較」去。" },
    ],
  },
  {
    question: "主要買的人比較像誰？",
    suggested: {
      label: "30–50 歲、會自己泡茶也會送禮的人",
      desc: "這是從網站受眾與商品組合（單包＋禮盒並存）推測的輪廓。選這個，調研會往「這群人平常在哪裡看茶類資訊」去。",
    },
    branches: [
      { label: "只買來送人的", desc: "偏禮品市場。選這個，調研會往「送禮場合與包裝規格」去。" },
      { label: "年輕嘗鮮客群", desc: "偏新客拓展。選這個，調研會往「年輕族群愛喝什麼茶飲、怎麼被吸引」去。" },
      { label: "賣給店家的", desc: "偏通路批發。選這個，調研會往「店家採購考量與最小訂購量」去。" },
    ],
  },
  {
    question: "最想避開什麼樣的講法？",
    suggested: {
      label: "誇大健康效果",
      desc: "茶類文案常見的地雷，也最容易踩到食品廣告法規的線。選這個，調研會往「哪些健康講法安全、哪些危險」去。",
    },
    branches: [
      { label: "比價", desc: "偏定價策略。選這個，調研會往「怎麼講價格不流於削價競爭」去。" },
      { label: "過度文青", desc: "偏語氣風格。選這個，調研會往「怎麼講產地故事又不流於空泛」去。" },
      { label: "強調得獎", desc: "偏背書型文案。選這個，調研會往「有哪些具體可查證的背書」去。" },
    ],
  },
  {
    question: "最主要的競爭對手長什麼樣？",
    suggested: {
      label: "同價位的產地直送小品牌",
      desc: "從商品頁的定價與敘事方式判斷，最直接的對手是同樣主打產區與小農故事的品牌。選這個，調研會往「這類小品牌都怎麼做行銷」去。",
    },
    branches: [
      { label: "量販通路的大品牌", desc: "偏規模化對手。選這個，調研會往「怎麼在價格與規模上做出區隔」去。" },
      { label: "手搖飲", desc: "偏替代性消費場合。選這個，調研會往「怎麼從手搖飲手上搶佔在家喝茶的場合」去。" },
      { label: "進口茶", desc: "偏產地故事對比。選這個，調研會往「本土產區故事怎麼講贏進口敘事」去。" },
    ],
  },
  {
    question: "這次調研最想先弄清楚哪一塊？",
    suggested: {
      label: "禮盒定位與競品比較",
      desc: "禮盒佔商品數一半，是目前看起來最需要說清楚定位的部分。選這個，調研會往「禮盒該怎麼定價與包裝」去。",
    },
    branches: [
      { label: "食品廣告的法規紅線", desc: "偏合規風險。選這個，調研會往「這個品類常見的法規地雷」去。" },
      { label: "通路策略", desc: "偏銷售佈局。選這個，調研會往「接下來該往哪些通路走」去。" },
      { label: "視覺風格", desc: "偏品牌識別。選這個，調研會往「包裝與內容視覺該怎麼定調」去。" },
    ],
  },
];

// ---------------------------------------------------------------------------
// 操作卡（script.py OPERATOR_CARDS／card_for）
// ---------------------------------------------------------------------------

const CARD_SHARED_STEP_1 = "開一個全新的對話。";
const CARD_SHARED_STEP_5 =
  "跑完之後它會先給一份調研報告、最後附一張表。報告留在對話裡自己看。複製表格時**不要用滑鼠框選畫面上的表格**（換行會被吃掉、貼回來會黏成一條）——用它的「複製」按鈕複製整份輸出，或把結果下載存成 .md／.txt 檔。回到系統後可以整段貼上，也可以直接上傳那個檔案。";
const CARD_SHARED_STEP_6 = "回到這個系統，按〔我跑完了，去貼回來〕。";

const DEEP_STEP_4: Record<"claude" | "chatgpt", string> = {
  claude:
    "送出前，先把輸入框下方的「研究」（Research）按鈕點亮再送出。它會自己上網查 10 到 30 分鐘，中間可能會問你問題，照實回答就好。（你的方案裡沒有這個按鈕的話，直接送出也可以，查得會淺一點但一樣能用；這個功能每個月有次數限制，用在深度調研上最划算。）",
  chatgpt:
    "送出前，先點輸入框的「＋」、選「深入研究」（Deep research）再送出。它會自己上網查 10 到 30 分鐘，中間可能會問你問題，照實回答就好。（你的方案裡沒有這個選項的話，直接送出也可以，查得會淺一點但一樣能用；這個功能每個月有次數限制，用在深度調研上最划算。）",
};

const OPERATOR_CARDS: Record<"claude" | "chatgpt", { title: string; steps: string[] }> = {
  claude: {
    title: "在 Claude 怎麼跑",
    steps: [
      CARD_SHARED_STEP_1,
      "把產品照拖進輸入框（可以一次多張）。",
      "貼上剛才複製的那段文字。",
      "送出，等它跑完。中間它可能會問你問題，照實回答就好。",
      CARD_SHARED_STEP_5,
      CARD_SHARED_STEP_6,
    ],
  },
  chatgpt: {
    title: "在 ChatGPT 怎麼跑",
    steps: [
      CARD_SHARED_STEP_1,
      "點輸入框左側的迴紋針或＋號，把產品照上傳進去（可以一次多張）。",
      "貼上剛才複製的那段文字。",
      "送出，等它跑完。中間它可能會問你問題，照實回答就好。",
      CARD_SHARED_STEP_5,
      CARD_SHARED_STEP_6,
    ],
  },
};

export function cardFor(provider: "claude" | "chatgpt", depth: "standard" | "deep"): { title: string; steps: string[] } {
  const card = OPERATOR_CARDS[provider];
  const steps = [...card.steps];
  if (depth === "deep") steps[3] = DEEP_STEP_4[provider];
  return { title: card.title, steps };
}

export const CARD_FALLBACK_NOTE =
  "直接把它給你的東西貼回來就好。系統會先檢查，格式不對會告訴你哪幾列有問題，也可以讓系統花一點錢幫你整理。";

// ---------------------------------------------------------------------------
// 貼回樣本（script.py 24 列成功樣本、3 處錯誤樣本）
// ---------------------------------------------------------------------------

const PASTE_HEADER = "種類 | 分類 | 標題 | 內容 | 適用範圍 | 佐證來源";

const SUCCESS_ROWS = [
  "品牌事實 | 定位 | 單一產區直送定位 | 主打單一產區的烏龍與紅茶，強調從茶園到茶杯的可追溯性，價格帶落在中高價位。 | 整個品牌 | 官網關於我們頁面",
  "品牌事實 | 受眾 | 送禮與自用兼具的輪廓 | 30 到 50 歲、自己會泡茶也會買來送人的族群，禮盒佔商品數約一半。 | 整個品牌 | 官網商品頁與粉專近期貼文",
  "品牌事實 | 語調 | 溫和少促銷的說話方式 | 粉專貼文多是產地與製程紀錄，幾乎不用驚嘆號與促銷字眼。 | 整個品牌 | 粉專近 20 篇貼文",
  "品牌事實 | 通路 | 目前的銷售通路 | 官網直營與線下茶行寄售並行，禮盒檔期會加開快閃櫃位。 | 整個品牌 | 官網門市資訊頁",
  "品牌事實 | 法規限制 | 「幫助代謝」用語需要佐證 | 商品頁出現「幫助代謝」字樣，屬於功能性宣稱，依食品安全衛生管理法需要有依據才能使用，目前查不到來源。 | 整個品牌 | 官網商品頁",
  "品牌事實 | 視覺基礎 | 包裝視覺的共通元素 | 四款茶的外包裝共用同一套牛皮紙感標籤與手寫體品牌字，禮盒版加燙金線條。 | 整個品牌 | 官網商品頁圖片",
  "品牌事實 | 定位 | 價格帶落點 | 單包茶葉 150 元上下、禮盒 880 元起，比同通路的量販茶包高約四成。 | 整個品牌 | 官網商品頁",
  "品牌事實 | 通路 | 尚未開放電商平台 | 目前沒有蝦皮或其他電商平台的官方賣場，詢問度高但還沒開賣。 | 整個品牌 | 粉專近期留言",
  "品牌事實 | 受眾 | 詢問度較高的族群 | 粉專訊息中詢問送禮包裝與大量採購的比例明顯高於詢問口味的比例。 | 整個品牌 | 粉專私訊紀錄摘要",
  `產品事實 | 核心資訊 | 規格與沖泡方式 | 一包 150 公克，適合冷泡與熱沖兩種方式，包裝內附簡易沖泡說明卡。 | ${MOCK_PRODUCT_NAME} | 官網商品頁`,
  `產品事實 | 作用機制 | 焙製方式 | 中焙火烏龍，茶葉為手採一心二葉，日曬與烘焙比例會依季節微調。 | ${MOCK_PRODUCT_NAME} | 官網商品頁與製茶紀錄`,
  `產品事實 | 差異化 | 與其他茶品的差別 | 相較於其他三款茶，這款焙火程度最重，回甘最明顯，是店內詢問度最高的品項。 | ${MOCK_PRODUCT_NAME} | 粉專近期貼文`,
  `產品事實 | 使用情境 | 常見的飲用時機 | 冷泡版本在夏季詢問度提高，多數顧客用來取代含糖手搖飲。 | ${MOCK_PRODUCT_NAME} | 粉專留言摘要`,
  `產品事實 | 目標客群 | 主要回購族群 | 30 歲以上、辦公室常備茶葉的上班族，回購頻率約每兩個月一次。 | ${MOCK_PRODUCT_NAME} | 官網會員訂單紀錄摘要`,
  `產品事實 | 視覺風格 | 包裝配色 | 使用茶褐色與牛皮紙感標籤，與其他三款茶以色塊區分，方便貨架辨識。 | ${MOCK_PRODUCT_NAME} | 官網商品頁圖片`,
  "限制規則 | 禁用字詞 | 不得使用療效相關字眼 | 文案不得出現「幫助代謝」以外的療效字樣，例如「治療」「根治」，這些字眼目前完全查不到依據。 | 整個品牌 | 官網商品頁用語盤點",
  "限制規則 | 素材使用 | 產品照須為官方拍攝 | 所有產品外觀照片須使用官方提供的實拍照，不得用 AI 生成替代茶葉或包裝的外觀。 | 整個品牌 | 粉專置頂公告",
  "限制規則 | 語氣 | 避免過度文青的形容 | 文案避免使用「療癒」「歲月靜好」這類抽象形容詞，改用具體的產地與製程描述。 | 整個品牌 | 粉專貼文風格觀察",
  "限制規則 | 視覺 | 禮盒版需保留燙金線條 | 禮盒版包裝設計需保留現行的燙金線條元素，用於維持與其他禮盒商品的識別度。 | 整個品牌 | 官網商品頁圖片",
  `宣稱 | 可用 | 單一產區直送，附產地標示 | 每包茶葉包裝上都印有茶園產地與採收季節，可追溯到單一茶園。 | ${MOCK_PRODUCT_NAME} | 官網商品頁產地標示`,
  `宣稱 | 可用 | 手採一心二葉 | 茶葉為人工採摘的一心二葉等級，非機採。 | ${MOCK_PRODUCT_NAME} | 製茶紀錄摘要`,
  "宣稱 | 高風險 | 幫助代謝 | 商品頁目前有這句話，但查不到具體依據，需要客戶提供檢驗或文獻佐證才能繼續使用。 | 整個品牌 | 無",
  `宣稱 | 高風險 | 適合天天飲用不影響睡眠 | 這句話涉及生理影響的宣稱，目前只有業主口頭說法，沒有第三方資料佐證。 | ${MOCK_PRODUCT_NAME} | 無`,
  "宣稱 | 禁用 | 可以取代西藥或保健品 | 這類宣稱明顯逾越食品可以宣稱的範圍，不得使用。 | 整個品牌 | 無",
];

export const PASTE_SAMPLE_SUCCESS = PASTE_HEADER + "\n" + SUCCESS_ROWS.join("\n");

const errorRows = [...SUCCESS_ROWS];
errorRows[6] =
  "品牌事實 | 功效 | 價格帶落點 | 單包茶葉 150 元上下、禮盒 880 元起，比同通路的量販茶包高約四成。 | 整個品牌 | 官網商品頁";
errorRows[11] = "產品事實 | 差異化 | 與其他茶品的差別 | 相較於其他三款茶，這款焙火程度最重，回甘最明顯，是店內詢問度最高的品項。";
errorRows[18] =
  "限制規則 | 視覺 | 禮盒版需保留燙金線條 | 禮盒版包裝設計需保留現行的燙金線條元素，用於維持與其他禮盒商品的識別度。 | 全系列 | 官網商品頁圖片";
export const PASTE_SAMPLE_ERRORS = PASTE_HEADER + "\n" + errorRows.join("\n");

export const PASTE_SAMPLE_FIXED = PASTE_SAMPLE_SUCCESS;

export const PASTE_SAMPLE_UNFIXABLE =
  "這次調研有點趕，先把重點寫給你：\n品牌走單一產區路線，價格中高，法規要注意功能性宣稱。\n細節之後再補。";

/** Mock「請 AI 幫我整理格式」：固定規則，非真的呼叫 LLM，只認得預寫的失敗樣本。 */
export function mockFix(rawText: string): string {
  return rawText.trim() === PASTE_SAMPLE_ERRORS.trim() ? PASTE_SAMPLE_FIXED : rawText;
}

/** 24 列成功樣本重複 4 輪，湊出「假資料要包含」節要求的 80 筆以上待處理清單
 * （測分頁與「剩餘全部先存成待確認」批次動作）。第 2、3 輪各挑 2 筆標成可能重複
 * （S4.59／S4.63 的 dup_hint 提示）。內容跟真實貼回內容脫鉤——這一步的畫面契約
 * 只要求「清單長什麼樣」，不要求跟使用者剛才貼的文字逐字對應。 */
export function buildReviewItems(): IntakeReviewItem[] {
  const items: IntakeReviewItem[] = [];
  let n = 0;
  for (let round = 0; round < 4; round++) {
    SUCCESS_ROWS.forEach((line, idx) => {
      const [kind, category, title, content, scope, evidence] = line.split("|").map((p) => p.trim());
      n += 1;
      items.push({
        id: nextId("review"),
        i: n,
        kind: kind as IntakeReviewItem["kind"],
        category,
        title: round === 0 ? title : `${title}（第 ${round + 1} 輪）`,
        content,
        scope,
        evidence,
        severity: kind === "限制規則" ? (idx % 2 === 0 ? "hard" : "soft") : null,
        dup_hint: round >= 1 && idx < 2 ? `可能與既有的「${title}」重複` : null,
      });
    });
  }
  return items;
}

// ---------------------------------------------------------------------------
// 草稿記錄
// ---------------------------------------------------------------------------

export interface DraftRecord extends IntakeDraft {}

const drafts = new Map<string, DraftRecord>();
const jobs = new Map<string, Map<IntakeJobKind, IntakeJobState>>();
const pendingPhotos = new Map<string, { name: string; size_mb: number }>();
const reviewItems = new Map<string, IntakeReviewItem[]>();

export function getReviewItems(brandId: string): IntakeReviewItem[] {
  return reviewItems.get(brandId) ?? [];
}

export function setReviewItems(brandId: string, items: IntakeReviewItem[]): void {
  reviewItems.set(brandId, items);
}

export function jobsFor(brandId: string): Map<IntakeJobKind, IntakeJobState> {
  if (!jobs.has(brandId)) jobs.set(brandId, new Map());
  return jobs.get(brandId)!;
}

export function getDraft(brandId: string): DraftRecord | undefined {
  return drafts.get(brandId);
}

export function setDraft(brandId: string, draft: DraftRecord): void {
  drafts.set(brandId, draft);
}

export function registerPendingPhoto(token: string, name: string, sizeMb: number): void {
  pendingPhotos.set(token, { name, size_mb: sizeMb });
}

export function resolvePhotoTokens(tokens: string[]): { name: string; token: string; size_mb: number }[] {
  return tokens
    .map((token) => {
      const p = pendingPhotos.get(token);
      return p ? { token, name: p.name, size_mb: p.size_mb } : null;
    })
    .filter((p): p is { token: string; name: string; size_mb: number } => p !== null);
}

const COST_LABEL: Record<IntakeJobKind, string> = {
  scan: "讀取網址與整理初步印象",
  question: "AI 出下一題",
  paste_fix: "AI 整理貼回格式",
};

export function estimateFor(kind: IntakeJobKind): number {
  return kind === "scan" ? COST_SCAN : kind === "question" ? COST_QUESTION : COST_PASTE_FIX;
}

export function recordCost(draft: DraftRecord, kind: IntakeJobKind, failed: boolean): void {
  const amount = estimateFor(kind);
  draft.cost_items.push({ label: COST_LABEL[kind], amount, failed } satisfies CostItem);
  if (!failed) draft.cost_spent = Math.round((draft.cost_spent + amount) * 100) / 100;
}

/** 新草稿：非陽春路徑起始輸入，或 W1b 重新調研共用（見 `intakeHandlers.ts`）。
 * `budgetLimit`／`costSpent` 讓呼叫端決定要不要一開場就接近上限（示範 S4.71-74）。 */
export function buildDraft(
  brandId: string,
  brandName: string,
  fields: { description: string; urls: string[]; photos: { name: string; token: string; size_mb: number }[] },
  opts?: { budgetLimit?: number; costSpent?: number; isRestart?: boolean; createdProductNames?: string[] },
): DraftRecord {
  const urlResults: UrlResult[] = fields.urls
    .filter((u) => u.trim())
    .map((url, i) => ({ url, ok: i !== 1 })); // 第 2 個網址示範讀取失敗，供收合明細測試
  return {
    id: nextId("draft"),
    brand_id: brandId,
    brand_name: brandName,
    step: 2,
    completed: false,
    is_restart: opts?.isRestart ?? false,
    description: fields.description,
    urls: fields.urls,
    photos: fields.photos.map((p) => ({ token: p.token, name: p.name, size_mb: p.size_mb })),
    scan_done: false,
    scan_impressions: [],
    scan_products: [],
    created_product_names: opts?.createdProductNames ?? [],
    url_results: urlResults,
    qa_done: false,
    current_q: null,
    answers: [],
    question_index: 0,
    handoff_depth: null,
    handoff_generated: false,
    handoff_prompt: null,
    paste_raw: "",
    paste_errors: [],
    paste_fix_used: false,
    pending_item_count: 0,
    budget_limit: opts?.budgetLimit ?? DEFAULT_BUDGET,
    cost_spent: opts?.costSpent ?? 0,
    cost_items: [],
  };
}

// ---------------------------------------------------------------------------
// 預先種一個「進行中草稿」品牌（票 B3-intake「假資料要包含」節）：長品牌名、超長描述、
// 5 個網址其中一個超長、預算貼近上限（示範 S4.71-74 超限攔截）、1 個已建立的偵測產品。
// ---------------------------------------------------------------------------

export const SEED_BRAND_ID = "mock-brand";
const SEED_BRAND_NAME = "測試用超長品牌名稱有限公司・旗艦生活風格系列測試品牌";
const SEED_DESCRIPTION =
  "這是一家從自家茶園起家的製茶品牌，堅持單一產區直送、從採摘到烘焙全程自己把關，希望讓消費者喝到看得見產地故事的茶。目前主力是烏龍與紅茶兩條產品線，禮盒與單包並行銷售，禮盒主要走送禮市場，單包則鎖定辦公室與居家的日常沖泡需求。品牌一直想把「產地可追溯」這件事講得更清楚，也想釐清在同價位帶的競品都怎麼做行銷、怎麼講故事而不流於空泛。過去曾經因為文案裡出現「幫助代謝」這類字眼被提醒可能踩到食品廣告法規的線，所以這次調研特別想弄清楚哪些健康相關的講法是安全的、哪些是危險的，避免之後的廣告素材又踩到同樣的地雷。除此之外，也想知道年輕客群對這種偏傳統的茶葉品牌接受度如何，未來是否有機會往外拓展新的客群，而不只是依賴既有的送禮與自用族群。這一段描述特意寫得比較長，用來測試畫面上這一欄位在很長的情況下排版會不會跑掉。";
const SEED_URLS = [
  "https://example.com/brand/about",
  "https://example.com/brand/products/oolong",
  "https://example.com/brand/products/gift-box-collection-with-a-very-long-slug-for-testing-how-the-details-panel-handles-an-unusually-long-url-that-might-otherwise-overflow-the-layout",
  "https://example.com/brand/store-locations",
  "https://facebook.com/example-brand-page",
];

export function seedMockBrand(): void {
  if (getDraft(SEED_BRAND_ID)) return;
  const draft = buildDraft(
    SEED_BRAND_ID,
    SEED_BRAND_NAME,
    { description: SEED_DESCRIPTION, urls: SEED_URLS, photos: [] },
    { budgetLimit: 6.35, costSpent: 6.0, createdProductNames: [MOCK_PRODUCT_NAME] },
  );
  setDraft(SEED_BRAND_ID, draft);
}
