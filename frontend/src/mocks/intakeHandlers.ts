/** 路由表（票 B3-intake）：契約「要新增的 API」節列的端點在這裡登記，`mocks/index.tsx`
 * import 這個檔案把路由掛進 `network.ts` 的攔截器。三種背景工作（初掃／出下一題／貼回
 * 修格式）共用同一套「先檢查超限、沒超限才啟動、`setTimeout` 模擬跑一段時間」的邏輯
 * （契約「背景工作機制」節），見 `runScan`／`runQuestion`／`runPasteFix` 三個小函式，
 * 都疊在 `simulateJob` 這顆共用核心上——三個真呼叫端才抽這一層，不是預先設計。 */
import type { IntakeDraft, IntakeJobKind, IntakeJobState, IntakeReviewItem, LimitBlock } from "@/lib/intakeApi";
import {
  buildDraft,
  buildReviewItems,
  cardFor,
  estimateFor,
  getDraft,
  getReviewItems,
  jobsFor,
  MAX_QUESTIONS,
  mockFix,
  nextId,
  QUESTIONS,
  recordCost,
  registerPendingPhoto,
  resolvePhotoTokens,
  SCAN_DETECTED_PRODUCTS,
  SCAN_IMPRESSIONS,
  seedMockBrand,
  setDraft,
  setReviewItems,
  type DraftRecord,
} from "./intakeData";
import { countDataLines, maybeReflow, parsePaste } from "./intakeParse";
import { buildPrompt } from "./intakePrompt";
import { envelope, errorResponse, jsonResponse, registerRoute } from "./network";
import { getActionFailure, getScenario } from "./state";

seedMockBrand();

const MISSING_KEY_MESSAGE = "尚未設定 AI 金鑰，請到「設定」頁填入後再試一次";

function idleJob(): IntakeJobState {
  return { status: "done", stage: "", started_at: new Date().toISOString(), usual_range_text: "", error: null };
}

async function readBody(init?: RequestInit): Promise<Record<string, unknown>> {
  if (!init?.body) return {};
  try {
    return JSON.parse(String(init.body)) as Record<string, unknown>;
  } catch {
    return {};
  }
}

function wouldExceed(draft: DraftRecord, kind: IntakeJobKind): boolean {
  return Math.round((draft.cost_spent + estimateFor(kind)) * 100) / 100 > draft.budget_limit;
}

function limitBlockFor(draft: DraftRecord, kind: IntakeJobKind): LimitBlock {
  return {
    kind,
    amount: estimateFor(kind),
    cost_spent: draft.cost_spent,
    budget_limit: draft.budget_limit,
    suggested_limit: Math.round((draft.budget_limit + 30) * 100) / 100,
  };
}

const USUAL_RANGE: Record<IntakeJobKind, string> = {
  scan: "20 到 40 秒",
  question: "10 到 20 秒",
  paste_fix: "10 到 20 秒",
};

const STAGE_START: Record<IntakeJobKind, string> = {
  scan: "讀取網址中",
  question: "正在準備下一題",
  paste_fix: "正在請 AI 整理格式",
};

/** 三種背景工作共用核心：超限就回傳攔截卡片資料、不啟動；否則掛 running，跑一段時間後
 * 依「動作失敗」開關決定完成或失敗（模擬 AI 無回應）。`onSuccess` 是各自的完成後續處理。 */
function simulateJob(
  brandId: string,
  kind: IntakeJobKind,
  draft: DraftRecord,
  durationMs: number,
  onSuccess: () => void,
  midStage?: { text: string; delayMs: number },
): { limit_block: LimitBlock | null } {
  if (wouldExceed(draft, kind)) return { limit_block: limitBlockFor(draft, kind) };
  const willFail = getActionFailure();
  const startedAt = new Date().toISOString();
  const usualRange = USUAL_RANGE[kind];
  jobsFor(brandId).set(kind, { status: "running", stage: STAGE_START[kind], started_at: startedAt, usual_range_text: usualRange, error: null });

  if (midStage) {
    setTimeout(() => {
      const job = jobsFor(brandId).get(kind);
      if (job && job.status === "running") jobsFor(brandId).set(kind, { ...job, stage: midStage.text });
    }, midStage.delayMs);
  }

  setTimeout(() => {
    recordCost(draft, kind, willFail);
    if (willFail) {
      jobsFor(brandId).set(kind, {
        status: "failed",
        stage: STAGE_START[kind],
        started_at: startedAt,
        usual_range_text: usualRange,
        error: MISSING_KEY_MESSAGE,
      });
      return;
    }
    onSuccess();
    jobsFor(brandId).set(kind, { status: "done", stage: "完成", started_at: startedAt, usual_range_text: usualRange, error: null });
  }, durationMs);

  return { limit_block: null };
}

function runScan(brandId: string, draft: DraftRecord) {
  return simulateJob(
    brandId,
    "scan",
    draft,
    5000,
    () => {
      // 空狀態開關（S4.20）：這次沒讀到可用內容——網址都讀不到、印象與偵測產品皆空。
      const empty = getScenario() === "empty";
      draft.scan_impressions = empty ? [] : SCAN_IMPRESSIONS;
      draft.scan_products = empty ? [] : SCAN_DETECTED_PRODUCTS;
      if (empty) draft.url_results = draft.url_results.map((r) => ({ ...r, ok: false }));
      draft.scan_done = true;
    },
    { text: "整理初步印象", delayMs: 2500 },
  );
}

function runQuestion(brandId: string, draft: DraftRecord) {
  return simulateJob(brandId, "question", draft, 3000, () => {
    if (draft.question_index >= QUESTIONS.length || draft.question_index >= MAX_QUESTIONS) {
      draft.qa_done = true;
      draft.current_q = null;
    } else {
      draft.current_q = QUESTIONS[draft.question_index];
    }
  });
}

function finishPasteAttempt(brandId: string, draft: DraftRecord, text: string) {
  const reflowed = maybeReflow(text);
  const known = new Set(draft.created_product_names);
  const [rows, errors] = parsePaste(reflowed, known, draft.brand_name);
  draft.paste_raw = text;
  draft.paste_errors = errors;
  if (rows) {
    draft.step = 5;
    if (draft.pending_item_count === 0) {
      const items = buildReviewItems();
      setReviewItems(brandId, items);
      draft.pending_item_count = items.length;
    }
  }
  return { errors, data_line_count: countDataLines(reflowed) };
}

function runPasteFix(brandId: string, draft: DraftRecord) {
  return simulateJob(brandId, "paste_fix", draft, 3000, () => {
    draft.paste_fix_used = true;
    finishPasteAttempt(brandId, draft, mockFix(draft.paste_raw));
  });
}

function requireDraft(brandId: string): DraftRecord | null {
  return getDraft(brandId) ?? null;
}

// ---- 起始輸入 ----

const PHOTO_EXTS = ["jpg", "jpeg", "png", "webp"];

registerRoute("POST", /^\/api\/intake\/photos$/, async (_m, init) => {
  const form = init?.body as FormData;
  const file = form.get("photo") as File | null;
  if (!file) return errorResponse(400, "請選擇檔案。");
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (!PHOTO_EXTS.includes(ext)) {
    return errorResponse(400, `「${file.name}」不是支援的檔案格式，請上傳 jpg、jpeg、png 或 webp 檔。`);
  }
  const sizeMb = Math.max(0.1, Math.round((file.size / 1024 / 1024) * 100) / 100);
  if (sizeMb > 10) return errorResponse(400, `「${file.name}」超過 10MB，請換一張較小的照片。`);
  const token = nextId("photo");
  registerPendingPhoto(token, file.name, sizeMb);
  return jsonResponse({ token, name: file.name, size_mb: sizeMb });
});

function invalidUrl(urls: string[]): string | null {
  return urls.find((u) => !/^https?:\/\//.test(u)) ?? null;
}

registerRoute("POST", /^\/api\/intake\/brands$/, async (_m, init) => {
  const form = init?.body as FormData;
  const brandName = String(form.get("brand_name") ?? "").trim();
  if (!brandName) return errorResponse(400, "請填寫品牌名稱。");
  const description = String(form.get("description") ?? "").trim();
  const urls = form.getAll("urls").map(String).filter((u) => u.trim());
  const bad = invalidUrl(urls);
  if (bad) return errorResponse(400, `「${bad}」不是有效的網址，請以 https:// 或 http:// 開頭。`);
  const photoTokens = form.getAll("photo_tokens").map(String);
  const photos = resolvePhotoTokens(photoTokens);
  const brandId = nextId("brand");

  if (!description && urls.length === 0 && photos.length === 0) {
    return jsonResponse({ brand_id: brandId, quick: true }); // S4.9 陽春路徑：不建草稿
  }
  setDraft(brandId, buildDraft(brandId, brandName, { description, urls, photos }));
  return jsonResponse({ brand_id: brandId, quick: false });
});

registerRoute("POST", /^\/api\/intake\/brands\/([^/]+)\/restart$/, async (match, init) => {
  const brandId = match[1];
  const existing = requireDraft(brandId);
  if (existing && !existing.completed) {
    return jsonResponse({ quick: false, already_running: true }); // S4.12：不開第二輪
  }
  const form = init?.body as FormData;
  const description = String(form.get("description") ?? "").trim();
  const urls = form.getAll("urls").map(String).filter((u) => u.trim());
  const bad = invalidUrl(urls);
  if (bad) return errorResponse(400, `「${bad}」不是有效的網址，請以 https:// 或 http:// 開頭。`);
  const photoTokens = form.getAll("photo_tokens").map(String);
  const newPhotos = resolvePhotoTokens(photoTokens);
  const brandName = existing?.brand_name ?? "既有品牌";
  const prevPhotos = existing?.photos ?? [];

  if (!description && urls.length === 0 && newPhotos.length === 0 && prevPhotos.length === 0) {
    return jsonResponse({ quick: true });
  }
  const draft = buildDraft(
    brandId,
    brandName,
    { description, urls, photos: [...prevPhotos.map((p) => ({ name: p.name, token: p.token, size_mb: p.size_mb })), ...newPhotos] },
    { isRestart: true, budgetLimit: existing?.budget_limit, createdProductNames: existing?.created_product_names },
  );
  setDraft(brandId, draft);
  return jsonResponse({ quick: false });
});

registerRoute("GET", /^\/api\/intake\/brands\/([^/]+)\/draft$/, (match) => {
  const draft = requireDraft(match[1]);
  if (!draft) return errorResponse(404, "找不到這個品牌的建檔進度。");
  return jsonResponse(envelope(draft));
});

// ---- 初掃 ----

registerRoute(
  "POST",
  /^\/api\/intake\/brands\/([^/]+)\/scan\/start$/,
  (match) => {
    const brandId = match[1];
    const draft = requireDraft(brandId);
    if (!draft) return errorResponse(404, "找不到這個品牌的建檔進度。");
    if (draft.scan_done) return jsonResponse({ limit_block: null });
    return jsonResponse(runScan(brandId, draft));
  },
  { skipAutoFail: true },
);

registerRoute("GET", /^\/api\/intake\/brands\/([^/]+)\/scan\/status$/, (match) =>
  jsonResponse(envelope(jobsFor(match[1]).get("scan") ?? idleJob())),
);

registerRoute("POST", /^\/api\/intake\/brands\/([^/]+)\/scan\/skip$/, (match) => {
  const draft = requireDraft(match[1]);
  if (!draft) return errorResponse(404, "找不到這個品牌的建檔進度。");
  draft.scan_done = true;
  draft.scan_impressions = [];
  draft.scan_products = [];
  jobsFor(match[1]).delete("scan");
  return new Response(null, { status: 204 });
});

registerRoute("POST", /^\/api\/intake\/brands\/([^/]+)\/scan\/products$/, async (match, init) => {
  const draft = requireDraft(match[1]);
  if (!draft) return errorResponse(404, "找不到這個品牌的建檔進度。");
  const body = await readBody(init);
  const names = Array.isArray(body.names) ? (body.names as string[]) : [];
  let created = 0;
  names.forEach((n) => {
    if (!draft.created_product_names.includes(n)) {
      draft.created_product_names.push(n);
      created += 1;
    }
  });
  return jsonResponse({ created_count: created });
});

// ---- 引導問答 ----

registerRoute(
  "POST",
  /^\/api\/intake\/brands\/([^/]+)\/question\/start$/,
  (match) => {
    const brandId = match[1];
    const draft = requireDraft(brandId);
    if (!draft) return errorResponse(404, "找不到這個品牌的建檔進度。");
    draft.step = Math.max(draft.step, 3) as IntakeDraft["step"]; // 使用者已經在畫面上進到步驟 3
    if (draft.qa_done || draft.current_q) return jsonResponse({ limit_block: null });
    return jsonResponse(runQuestion(brandId, draft));
  },
  { skipAutoFail: true },
);

registerRoute("GET", /^\/api\/intake\/brands\/([^/]+)\/question\/status$/, (match) =>
  jsonResponse(envelope(jobsFor(match[1]).get("question") ?? idleJob())),
);

registerRoute("POST", /^\/api\/intake\/brands\/([^/]+)\/question\/answer$/, async (match, init) => {
  const draft = requireDraft(match[1]);
  if (!draft) return errorResponse(404, "找不到這個品牌的建檔進度。");
  const q = draft.current_q;
  if (!q) return errorResponse(400, "目前沒有可回答的題目。");
  const body = await readBody(init);
  const choice = String(body.choice ?? "");
  const note = String(body.note ?? "").trim();

  if (choice !== "skip") {
    if (!choice) return errorResponse(400, "請選一個選項。");
    if (choice === "other" && !note) return errorResponse(400, "你選了「我自己說」，請在補充欄寫一句你的想法。");
    const branchIdx = choice.startsWith("branch_") ? Number(choice.slice("branch_".length)) : -1;
    const choiceLabel =
      choice === "suggested" ? q.suggested.label : choice === "other" ? "我自己說" : q.branches[branchIdx]?.label ?? choice;
    draft.answers.push({ index: draft.question_index, question: q.question, choice_label: choiceLabel, note });
  }
  draft.question_index += 1;
  draft.current_q = null;
  jobsFor(match[1]).delete("question");
  return new Response(null, { status: 204 });
});

registerRoute("POST", /^\/api\/intake\/brands\/([^/]+)\/question\/skip-remaining$/, (match) => {
  const draft = requireDraft(match[1]);
  if (!draft) return errorResponse(404, "找不到這個品牌的建檔進度。");
  draft.qa_done = true;
  draft.current_q = null;
  jobsFor(match[1]).delete("question");
  return new Response(null, { status: 204 });
});

// ---- 交接包 ----

registerRoute("POST", /^\/api\/intake\/brands\/([^/]+)\/handoff$/, async (match, init) => {
  const draft = requireDraft(match[1]);
  if (!draft) return errorResponse(404, "找不到這個品牌的建檔進度。");
  const body = await readBody(init);
  const depth = body.depth === "deep" || body.depth === "standard" ? body.depth : null;
  if (!depth) return errorResponse(400, "請選擇要跑多深。");
  draft.handoff_depth = depth;
  draft.handoff_generated = true;
  draft.handoff_prompt = buildPrompt(draft, depth);
  draft.step = Math.max(draft.step, 4) as IntakeDraft["step"];
  return jsonResponse({ prompt_text: draft.handoff_prompt });
});

registerRoute("GET", /^\/api\/intake\/brands\/([^/]+)\/handoff\/(claude|chatgpt)$/, (match) => {
  const draft = requireDraft(match[1]);
  if (!draft) return errorResponse(404, "找不到這個品牌的建檔進度。");
  return jsonResponse(envelope(cardFor(match[2] as "claude" | "chatgpt", draft.handoff_depth ?? "standard")));
});

// ---- 貼回 ----

registerRoute("POST", /^\/api\/intake\/brands\/([^/]+)\/paste\/validate$/, async (match, init) => {
  const draft = requireDraft(match[1]);
  if (!draft) return errorResponse(404, "找不到這個品牌的建檔進度。");
  const body = await readBody(init);
  const rawText = String(body.raw_text ?? "");
  if (!rawText.trim()) return errorResponse(400, "請先貼上 AI 給你的表格內容。");
  return jsonResponse(finishPasteAttempt(match[1], draft, rawText));
});

registerRoute("POST", /^\/api\/intake\/brands\/([^/]+)\/paste\/resolve-scope$/, async (match, init) => {
  const draft = requireDraft(match[1]);
  if (!draft) return errorResponse(404, "找不到這個品牌的建檔進度。");
  const body = await readBody(init);
  const scopeName = String(body.scope_name ?? "");
  const action = body.action === "create_product" ? "create_product" : "assign_brand";
  if (action === "create_product") {
    if (scopeName && !draft.created_product_names.includes(scopeName)) draft.created_product_names.push(scopeName);
  } else {
    draft.paste_raw = draft.paste_raw.split(`| ${scopeName} |`).join(`| 整個品牌 |`);
  }
  return jsonResponse(finishPasteAttempt(match[1], draft, draft.paste_raw));
});

registerRoute(
  "POST",
  /^\/api\/intake\/brands\/([^/]+)\/paste\/fix\/start$/,
  (match) => {
    const brandId = match[1];
    const draft = requireDraft(brandId);
    if (!draft) return errorResponse(404, "找不到這個品牌的建檔進度。");
    return jsonResponse(runPasteFix(brandId, draft));
  },
  { skipAutoFail: true },
);

registerRoute("GET", /^\/api\/intake\/brands\/([^/]+)\/paste\/fix\/status$/, (match) =>
  jsonResponse(envelope(jobsFor(match[1]).get("paste_fix") ?? idleJob())),
);

// ---- 待處理清單 ----

registerRoute("GET", /^\/api\/intake\/brands\/([^/]+)\/review$/, (match) => {
  const draft = requireDraft(match[1]);
  if (!draft) return errorResponse(404, "找不到這個品牌的建檔進度。");
  return jsonResponse(envelope(getReviewItems(match[1])));
});

registerRoute("POST", /^\/api\/intake\/brands\/([^/]+)\/review\/pending-all$/, (match) => {
  const draft = requireDraft(match[1]);
  if (!draft) return errorResponse(404, "找不到這個品牌的建檔進度。");
  setReviewItems(match[1], []);
  draft.pending_item_count = 0;
  draft.completed = true;
  return new Response(null, { status: 204 });
});

registerRoute("GET", /^\/api\/intake\/brands\/([^/]+)\/review\/(\d+)$/, (match) => {
  const item = getReviewItems(match[1]).find((it) => it.i === Number(match[2]));
  if (!item) return errorResponse(404, "找不到這一筆。");
  return jsonResponse(envelope(item));
});

registerRoute("POST", /^\/api\/intake\/brands\/([^/]+)\/review\/(\d+)$/, async (match, init) => {
  const draft = requireDraft(match[1]);
  if (!draft) return errorResponse(404, "找不到這個品牌的建檔進度。");
  const items = getReviewItems(match[1]);
  const idx = items.findIndex((it) => it.i === Number(match[2]));
  if (idx === -1) return errorResponse(404, "找不到這一筆。");
  const body = await readBody(init);
  const outcome = body.outcome === "confirm" || body.outcome === "discard" ? body.outcome : "pending";
  const kind = String(body.kind ?? items[idx].kind) as IntakeReviewItem["kind"];
  const scope = String(body.scope ?? items[idx].scope);

  if (outcome !== "discard") {
    const title = String(body.title ?? "").trim();
    const content = String(body.content ?? "").trim();
    const category = String(body.category ?? "");
    if (!title) return errorResponse(400, "請填寫標題。");
    if (!content) return errorResponse(400, "請填寫內容。");
    if (!category) return errorResponse(400, "請選擇分類。");
    if (kind === "產品事實" && scope === "整個品牌") {
      return errorResponse(400, "產品事實要選一個產品，不能是「整個品牌」。");
    }
  }

  items.splice(idx, 1);
  setReviewItems(match[1], items);
  draft.pending_item_count = items.length;
  if (items.length === 0) draft.completed = true;
  return new Response(null, { status: 204 });
});

// ---- 花費上限 ----

registerRoute("POST", /^\/api\/intake\/brands\/([^/]+)\/budget$/, async (match, init) => {
  const draft = requireDraft(match[1]);
  if (!draft) return errorResponse(404, "找不到這個品牌的建檔進度。");
  const body = await readBody(init);
  if (body.limit === undefined || body.limit === null || body.limit === "") {
    return errorResponse(400, "請填寫上限金額。");
  }
  const limit = Number(body.limit);
  if (Number.isNaN(limit)) return errorResponse(400, "上限金額請填數字，例如 30。");
  if (limit < draft.cost_spent) {
    return errorResponse(400, `這次已經花了 US$ ${draft.cost_spent.toFixed(2)}，上限不能設得比它低。`);
  }
  draft.budget_limit = Math.round(limit * 100) / 100;
  return new Response(null, { status: 204 });
});

registerRoute(
  "POST",
  /^\/api\/intake\/brands\/([^/]+)\/budget\/raise$/,
  async (match, init) => {
    const brandId = match[1];
    const draft = requireDraft(brandId);
    if (!draft) return errorResponse(404, "找不到這個品牌的建檔進度。");
    const body = await readBody(init);
    const kind = (body.kind === "scan" || body.kind === "question" || body.kind === "paste_fix" ? body.kind : "scan") as IntakeJobKind;
    draft.budget_limit = Math.round((draft.budget_limit + 30) * 100) / 100;
    const runner = kind === "scan" ? runScan : kind === "question" ? runQuestion : runPasteFix;
    runner(brandId, draft); // 剛加了 30，這次一定不會再超限
    return jsonResponse({ job: jobsFor(brandId).get(kind) ?? idleJob() });
  },
  { skipAutoFail: true },
);

registerRoute("POST", /^\/api\/intake\/brands\/([^/]+)\/skip-remaining-ai$/, (match) => {
  const draft = requireDraft(match[1]);
  if (!draft) return errorResponse(404, "找不到這個品牌的建檔進度。");
  if (!draft.scan_done) {
    draft.scan_done = true;
    draft.scan_impressions = [];
    draft.scan_products = [];
  }
  draft.qa_done = true;
  draft.current_q = null;
  draft.step = 4;
  jobsFor(match[1]).clear();
  return new Response(null, { status: 204 });
});
