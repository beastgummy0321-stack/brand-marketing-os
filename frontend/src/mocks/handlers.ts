/** 路由表（票 B2-library）：契約列出的每個端點在這裡登記一筆，import 這個檔案就會把
 * 全部路由掛進 `network.ts` 的攔截器（副作用 import，見 `mocks/index.tsx`）。GET 讀
 * `libraryStore`（可變倉庫）；既有表單 POST 端點直接改 `libraryStore` 對應陣列，讓「新增
 * →存檔→下次讀取看得到」這條原型走得通，不是按下去沒反應。 */
import {
  ASSET_KINDS,
  BRAND_FACT_TYPES,
  CHANNEL_TYPES,
  CUSTOMER_VOICE_CHANNELS,
  optionLabel as label,
  RULE_TYPES,
  type ClaimType,
  type CustomerVoiceExtractionItem,
  type CustomerVoiceJobStatus,
  type LibraryAsset,
  type LibraryChannel,
  type LibraryCustomerVoice,
  type RuleSeverity,
} from "@/lib/libraryApi";
import { buildEmptyLibrary, libraryStore, nextId } from "./data";
import { envelope, errorResponse, jsonResponse, registerRoute } from "./network";
import { getActionFailure, getScenario } from "./state";

function scopeLabelFor(productId: string | null): string {
  if (!productId) return "整個品牌";
  return libraryStore.products.find((p) => p.id === productId)?.name ?? productId;
}

function currentLibrary() {
  return getScenario() === "empty" ? buildEmptyLibrary() : libraryStore;
}

function formValue(form: FormData, key: string): string {
  const v = form.get(key);
  return typeof v === "string" ? v : "";
}

// ---- 整包讀取 ----

registerRoute("GET", /^\/api\/library\/brands\/[^/]+$/, () => jsonResponse(envelope(currentLibrary())));

// ---- 品牌事實 ----

registerRoute("POST", /^\/brands\/[^/]+\/facts\/new$/, async (_m, init) => {
  const form = init?.body as FormData;
  libraryStore.facts.push({
    id: nextId("fact"),
    fact_type: formValue(form, "fact_type"),
    fact_type_label: label(BRAND_FACT_TYPES, formValue(form, "fact_type")),
    label: formValue(form, "label"),
    value: formValue(form, "value"),
    status: formValue(form, "status") === "confirmed" ? "confirmed" : "pending",
    confirmed_by: null,
    confirmed_at: null,
    stale_label: null,
    source_reference: formValue(form, "source_reference") || null,
  });
  return new Response(null, { status: 200 });
});

registerRoute("POST", /^\/brands\/[^/]+\/facts\/([^/]+)\/edit$/, async (match, init) => {
  const form = init?.body as FormData;
  const fact = libraryStore.facts.find((f) => f.id === match[1]);
  if (!fact) return errorResponse(404, "找不到這條事實");
  fact.fact_type = formValue(form, "fact_type");
  fact.fact_type_label = label(BRAND_FACT_TYPES, formValue(form, "fact_type"));
  fact.label = formValue(form, "label");
  fact.value = formValue(form, "value");
  fact.source_reference = formValue(form, "source_reference") || null;
  return new Response(null, { status: 200 });
});

registerRoute("POST", /^\/brands\/[^/]+\/facts\/([^/]+)\/confirm$/, async (match, init) => {
  const form = init?.body as FormData;
  const fact = libraryStore.facts.find((f) => f.id === match[1]);
  if (!fact) return errorResponse(404, "找不到這條事實");
  fact.status = "confirmed";
  fact.confirmed_by = formValue(form, "confirmed_by");
  fact.confirmed_at = new Date().toISOString();
  fact.stale_label = null;
  return new Response(null, { status: 200 });
});

registerRoute("POST", /^\/brands\/[^/]+\/facts\/([^/]+)\/delete$/, (match) => {
  libraryStore.facts = libraryStore.facts.filter((f) => f.id !== match[1]);
  return new Response(null, { status: 200 });
});

// ---- 限制規則 ----

registerRoute("POST", /^\/brands\/[^/]+\/rules\/new$/, async (_m, init) => {
  const form = init?.body as FormData;
  const productId = formValue(form, "product_id") || null;
  libraryStore.rules.push({
    id: nextId("rule"),
    rule_type: formValue(form, "rule_type"),
    rule_type_label: label(RULE_TYPES, formValue(form, "rule_type")),
    content: formValue(form, "content"),
    severity: (formValue(form, "severity") as RuleSeverity) || "soft",
    product_id: productId,
    scope_label: scopeLabelFor(productId),
    source_reference: formValue(form, "source_reference") || null,
  });
  return new Response(null, { status: 200 });
});

registerRoute("POST", /^\/brands\/[^/]+\/rules\/([^/]+)\/edit$/, async (match, init) => {
  const form = init?.body as FormData;
  const rule = libraryStore.rules.find((r) => r.id === match[1]);
  if (!rule) return errorResponse(404, "找不到這條規則");
  const productId = formValue(form, "product_id") || null;
  rule.rule_type = formValue(form, "rule_type");
  rule.rule_type_label = label(RULE_TYPES, formValue(form, "rule_type"));
  rule.content = formValue(form, "content");
  rule.severity = (formValue(form, "severity") as RuleSeverity) || "soft";
  rule.product_id = productId;
  rule.scope_label = scopeLabelFor(productId);
  rule.source_reference = formValue(form, "source_reference") || null;
  return new Response(null, { status: 200 });
});

registerRoute("POST", /^\/brands\/[^/]+\/rules\/([^/]+)\/delete$/, (match) => {
  libraryStore.rules = libraryStore.rules.filter((r) => r.id !== match[1]);
  return new Response(null, { status: 200 });
});

// ---- 宣稱 ----

registerRoute("POST", /^\/brands\/[^/]+\/claims\/new$/, async (_m, init) => {
  const form = init?.body as FormData;
  const productId = formValue(form, "product_id") || null;
  libraryStore.claims.push({
    id: nextId("claim"),
    claim_text: formValue(form, "claim_text"),
    claim_type: (formValue(form, "claim_type") as ClaimType) || "high_risk",
    product_id: productId,
    scope_label: scopeLabelFor(productId),
    evidence_source_reference: formValue(form, "evidence_source_reference") || null,
  });
  return new Response(null, { status: 200 });
});

registerRoute("POST", /^\/brands\/[^/]+\/claims\/([^/]+)\/edit$/, async (match, init) => {
  const form = init?.body as FormData;
  const claim = libraryStore.claims.find((c) => c.id === match[1]);
  if (!claim) return errorResponse(404, "找不到這條宣稱");
  const productId = formValue(form, "product_id") || null;
  claim.claim_text = formValue(form, "claim_text");
  claim.claim_type = (formValue(form, "claim_type") as ClaimType) || "high_risk";
  claim.product_id = productId;
  claim.scope_label = scopeLabelFor(productId);
  claim.evidence_source_reference = formValue(form, "evidence_source_reference") || null;
  return new Response(null, { status: 200 });
});

registerRoute("POST", /^\/brands\/[^/]+\/claims\/([^/]+)\/delete$/, (match) => {
  libraryStore.claims = libraryStore.claims.filter((c) => c.id !== match[1]);
  return new Response(null, { status: 200 });
});

// ---- 官方素材 ----
// 上傳的檔案本身沒有真後端可存，用 URL.createObjectURL 在瀏覽器端就地生一個可預覽的網址，
// 原型不必真的落地檔案也能看到剛傳的圖（重新整理後會失效，這是 blob: URL 的天生限制，
// 原型階段可接受，接真後端後這段連同整個 mocks/ 一起刪）。

registerRoute("POST", /^\/brands\/[^/]+\/assets\/new$/, async (_m, init) => {
  const form = init?.body as FormData;
  const file = form.get("file");
  const productId = formValue(form, "product_id") || null;
  const asset: LibraryAsset = {
    id: nextId("asset"),
    asset_kind: (formValue(form, "asset_kind") as LibraryAsset["asset_kind"]) || "other",
    asset_kind_label: label(ASSET_KINDS, formValue(form, "asset_kind")),
    title: formValue(form, "title") || null,
    product_id: productId,
    product_name: productId ? scopeLabelFor(productId) : null,
    file_url: file instanceof File ? URL.createObjectURL(file) : "",
  };
  libraryStore.assets.push(asset);
  return new Response(null, { status: 200 });
});

registerRoute("POST", /^\/brands\/[^/]+\/assets\/([^/]+)\/delete$/, (match) => {
  libraryStore.assets = libraryStore.assets.filter((a) => a.id !== match[1]);
  return new Response(null, { status: 200 });
});

// ---- 自有渠道 ----

registerRoute("POST", /^\/brands\/[^/]+\/channels\/new$/, async (_m, init) => {
  const form = init?.body as FormData;
  libraryStore.channels.push({
    id: nextId("channel"),
    channel_type: (formValue(form, "channel_type") as LibraryChannel["channel_type"]) || "website",
    channel_type_label: label(CHANNEL_TYPES, formValue(form, "channel_type")),
    name: formValue(form, "name"),
    identifier: formValue(form, "identifier"),
    status: formValue(form, "status") === "inactive" ? "inactive" : "active",
  });
  return new Response(null, { status: 200 });
});

registerRoute("POST", /^\/brands\/[^/]+\/channels\/([^/]+)\/edit$/, async (match, init) => {
  const form = init?.body as FormData;
  const channel = libraryStore.channels.find((c) => c.id === match[1]);
  if (!channel) return errorResponse(404, "找不到這個渠道");
  channel.channel_type = (formValue(form, "channel_type") as LibraryChannel["channel_type"]) || "website";
  channel.channel_type_label = label(CHANNEL_TYPES, formValue(form, "channel_type"));
  channel.name = formValue(form, "name");
  channel.identifier = formValue(form, "identifier");
  channel.status = formValue(form, "status") === "inactive" ? "inactive" : "active";
  return new Response(null, { status: 200 });
});

registerRoute("POST", /^\/brands\/[^/]+\/channels\/([^/]+)\/delete$/, (match) => {
  libraryStore.channels = libraryStore.channels.filter((c) => c.id !== match[1]);
  return new Response(null, { status: 200 });
});

// ---- 顧客原話 ----

registerRoute("POST", /^\/brands\/[^/]+\/customer-voice\/([^/]+)\/archive$/, (match) => {
  const cv = libraryStore.customer_voices.find((v) => v.id === match[1]);
  if (cv) cv.status = cv.status === "archived" ? "active" : "archived";
  return new Response(null, { status: 200 });
});

registerRoute("POST", /^\/brands\/[^/]+\/customer-voice\/([^/]+)\/delete$/, (match) => {
  libraryStore.customer_voices = libraryStore.customer_voices.filter((v) => v.id !== match[1]);
  return new Response(null, { status: 200 });
});

/** 貼入＋AI 抽取背景任務（契約 S5.40–S5.42）：POST 立即回 job_key，不等抽取完成；
 * 完成／失敗結果由 GET jobs/:key 輪詢拿到。用「動作失敗」開關決定這次背景任務的結局——
 * 沿用既有開關語意（寫入動作失敗），不另開第三顆開關。真後端接上後這裡的 setTimeout
 * 會換成真的背景執行緒＋收件匣通知（見契約「要新增的 API」節）。 */
const customerVoiceJobs = new Map<string, CustomerVoiceJobStatus>();

registerRoute("POST", /^\/api\/library\/brands\/[^/]+\/customer-voice$/, async (_m, init) => {
  const body = init?.body ? JSON.parse(String(init.body)) : {};
  const jobKey = nextId("cv-job");
  const shouldFail = getActionFailure();
  customerVoiceJobs.set(jobKey, { status: "running" });

  setTimeout(() => {
    if (shouldFail) {
      customerVoiceJobs.set(jobKey, {
        status: "failed",
        message: "AI 抽取失敗，請稍後再試一次（模擬逾時）。",
      });
      return;
    }
    const extraction: CustomerVoiceExtractionItem[] = [
      {
        task_layer: "functional",
        quote: "「用了兩週之後真的有感，會考慮回購」",
        insight: "顧客在意實際見效時間。",
        signal: "unprompted",
      },
    ];
    const result: LibraryCustomerVoice = {
      id: nextId("cv"),
      source_channel: body.source_channel ?? "other",
      source_channel_label: label(CUSTOMER_VOICE_CHANNELS, body.source_channel ?? "other"),
      source_detail: body.source_detail || null,
      raw_text: body.raw_text ?? "",
      status: "active",
      extraction,
    };
    libraryStore.customer_voices.unshift(result);
    customerVoiceJobs.set(jobKey, { status: "done", result });
  }, 2500);

  return jsonResponse({ job_key: jobKey });
});

registerRoute(
  "GET",
  /^\/api\/library\/brands\/[^/]+\/customer-voice\/jobs\/([^/]+)$/,
  (match) => jsonResponse(customerVoiceJobs.get(match[1]) ?? { status: "running" }),
);

// ---- 品牌資料側板 ----

registerRoute("POST", /^\/brands\/[^/]+\/edit$/, async (_m, init) => {
  const form = init?.body as FormData;
  libraryStore.brand.name = formValue(form, "name");
  libraryStore.brand.client_name = formValue(form, "client_name") || null;
  libraryStore.brand.status = formValue(form, "status") === "archived" ? "archived" : "active";
  // persona 不存檔，只是前端填表捷徑（契約 S5.46），這裡收到也不寫回 libraryStore。
  libraryStore.brand.market_region = formValue(form, "market_region") || null;
  libraryStore.brand.conversion_goal = formValue(form, "conversion_goal") || null;
  libraryStore.brand.industry = formValue(form, "industry") || null;
  return new Response(null, { status: 200 });
});

registerRoute("POST", /^\/brands\/[^/]+\/delete$/, async (_m, init) => {
  const form = init?.body as FormData;
  if (formValue(form, "confirm_name") !== libraryStore.brand.name) {
    return errorResponse(400, "品牌名稱輸入不相符");
  }
  return new Response(null, { status: 200 });
});
