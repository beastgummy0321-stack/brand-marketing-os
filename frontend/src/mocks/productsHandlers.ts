/** 路由表（票 B2-products）：契約「要新增的 API」節列的端點在這裡登記，`mocks/index.tsx`
 * import 這個檔案把路由掛進 `network.ts` 的攔截器——跟品牌智庫的 `handlers.ts` 是兩份獨立
 * 檔案，各自對應各自的 feature，都掛在同一個 `mocks/` 目錄底下（單一假資料目錄，不是單一
 * 檔案；`index.tsx` 仍是唯一入口）。四分頁「一次整包讀」，這裡沒有 facts/economics-view/
 * rules/claims 四支分頁 GET（契約表列的是後端未來的路由邊界，原型合併進整包讀，見
 * `lib/productsApi.ts` 檔頭說明）。 */
import {
  COST_PRODUCT_HANDOFF_FIX,
  optionLabel as label,
  PRODUCT_FACT_TYPES,
  type ProductEconomics,
  type ProductFact,
} from "@/lib/productsApi";
import { envelope, errorResponse, jsonResponse, registerRoute } from "./network";
import { findProduct, nextId, productDeleteImpact, productDetail, productsStore, researchJobs } from "./productsData";
import { getActionFailure, getScenario } from "./state";

function formValue(body: Record<string, unknown>, key: string): string {
  const v = body[key];
  return typeof v === "string" ? v : "";
}

function noContent(): Response {
  return new Response(null, { status: 204 });
}

async function readBody(init?: RequestInit): Promise<Record<string, unknown>> {
  if (!init?.body) return {};
  try {
    return JSON.parse(String(init.body)) as Record<string, unknown>;
  } catch {
    return {};
  }
}

/** 花費超過上限的人話訊息，格式逐字對照 `app/core/settings.py:154-157`（查證日 2026-08-11）。
 * 假資料層固定用一組虛構的已花金額／上限，不接真的設定頁資料。 */
function budgetExceededMessage(action: string, cost: number): string {
  const spent = 12.4;
  const limit = 12.5;
  return (
    `這個品牌目前已經花了 US$ ${spent.toFixed(2)}，${action}預估要花 US$ ${cost.toFixed(2)}，` +
    `會超過設定頁目前的 US$ ${limit.toFixed(2)} 花費上限。可以到「設定」頁調高上限，` +
    `或先用「新增這個產品」手動建立。`
  );
}

// ---- 產品清單 ----

registerRoute("GET", /^\/api\/products\/brands\/[^/]+$/, () => {
  const list = getScenario() === "empty" ? [] : productsStore.map((r) => ({
    id: r.id,
    name: r.name,
    status: r.status,
    fact_count: r.facts.length,
    pending_fact_count: r.facts.filter((f) => f.status === "pending").length,
    economics_status: r.economics === null ? ("none" as const) : r.economics.status,
  }));
  return jsonResponse(envelope(list));
});

registerRoute("POST", /^\/api\/products\/brands\/[^/]+$/, async (_m, init) => {
  const body = await readBody(init);
  const id = nextId("product");
  productsStore.push({
    id,
    name: formValue(body, "name"),
    status: "active",
    knowledge_version: 1,
    latest_source_url: formValue(body, "source_url") || null,
    facts: [],
    economics: null,
    claims: [],
  });
  return jsonResponse({ id });
});

// ---- AI 調研新增：同步建立產品＋背景啟動調研（拿不準的點 1，本檔採契約目前的設計 A）----

registerRoute(
  "POST",
  /^\/api\/products\/brands\/[^/]+\/research$/,
  async (_m, init) => {
    const body = await readBody(init);
    const id = nextId("product");
    const sourceUrl = formValue(body, "source_url");
    productsStore.push({
      id,
      name: formValue(body, "name"),
      status: "active",
      knowledge_version: 1,
      latest_source_url: sourceUrl || null,
      facts: [],
      economics: null,
      claims: [],
    });
    startResearchJob(id);
    return jsonResponse({ product_id: id });
  },
  { skipAutoFail: true },
);

registerRoute(
  "POST",
  /^\/api\/products\/brands\/[^/]+\/products\/([^/]+)\/rescan$/,
  async (match, init) => {
    const productId = match[1];
    const record = findProduct(productId);
    if (!record) return errorResponse(404, "找不到這個產品");
    const body = await readBody(init);
    record.latest_source_url = formValue(body, "source_url") || record.latest_source_url;
    const existing = researchJobs.get(productId);
    if (!existing || existing.status === "done" || existing.status === "failed") {
      startResearchJob(productId);
    } // 已在跑（waiting／running）：同一個 key 不重新啟動。
    return jsonResponse({});
  },
  { skipAutoFail: true },
);

/** 背景調研：立即掛 running，模擬跑 6 秒後依「動作失敗」開關決定完成或失敗（S6.29–S6.31）。 */
function startResearchJob(productId: string): void {
  const willFail = getActionFailure();
  researchJobs.set(productId, {
    status: "running",
    stage: "讀取網址中",
    started_at: new Date().toISOString(),
    usual_range_text: "30 到 60 秒",
    error: null,
    added_count: null,
    price_created: false,
  });
  setTimeout(() => {
    const record = findProduct(productId);
    if (!record) return; // 產品同時被刪掉，放棄回填。
    if (willFail) {
      researchJobs.set(productId, {
        status: "failed",
        stage: "整理事實中",
        started_at: new Date(Date.now() - 6000).toISOString(),
        usual_range_text: "30 到 60 秒",
        error: budgetExceededMessage("這次調研", 0.3),
        added_count: null,
        price_created: false,
      });
      return;
    }
    const added: ProductFact[] = [0, 1, 2].map((i) => {
      const factType = PRODUCT_FACT_TYPES[i % PRODUCT_FACT_TYPES.length][0];
      return {
        id: nextId("pfact"),
        fact_type: factType,
        fact_type_label: label(PRODUCT_FACT_TYPES, factType),
        label: `AI 調研新增：${label(PRODUCT_FACT_TYPES, factType)}`,
        value: "AI 從產品頁調研到的內容，待人工確認。",
        status: "pending",
        confirmed_by: null,
        confirmed_at: null,
        source_reference: record.latest_source_url,
      };
    });
    record.facts.push(...added);
    let priceCreated = false;
    if (record.economics === null) {
      record.economics = {
        selling_price: 690,
        fixed_cost: null,
        unit_variable_cost: null,
        shipping_cost: null,
        currency: "TWD",
        cpa_roas_basis: null,
        effective_from: null,
        status: "pending",
        confirmed_by: null,
      } satisfies ProductEconomics;
      priceCreated = true;
    }
    researchJobs.set(productId, {
      status: "done",
      stage: "完成",
      started_at: new Date(Date.now() - 6000).toISOString(),
      usual_range_text: "30 到 60 秒",
      error: null,
      added_count: added.length,
      price_created: priceCreated,
    });
  }, 6000);
}

registerRoute("GET", /^\/api\/products\/brands\/[^/]+\/products\/([^/]+)\/research-status$/, (match) => {
  const job = researchJobs.get(match[1]);
  return jsonResponse(
    envelope(
      job ?? {
        status: "done",
        stage: "",
        started_at: new Date().toISOString(),
        usual_range_text: "",
        error: null,
        added_count: null,
        price_created: false,
      },
    ),
  );
});

// ---- 產品詳情（整包） ----

registerRoute("GET", /^\/api\/products\/brands\/[^/]+\/products\/([^/]+)$/, (match) => {
  const detail = productDetail(match[1]);
  if (!detail) return errorResponse(404, "找不到這個產品");
  return jsonResponse(envelope(detail));
});

registerRoute("POST", /^\/api\/products\/brands\/[^/]+\/products\/([^/]+)\/archive$/, (match) => {
  const record = findProduct(match[1]);
  if (!record) return errorResponse(404, "找不到這個產品");
  record.status = record.status === "archived" ? "active" : "archived";
  return noContent();
});

// ---- 產品事實 ----

registerRoute("POST", /^\/api\/products\/brands\/[^/]+\/products\/([^/]+)\/facts$/, async (match, init) => {
  const record = findProduct(match[1]);
  if (!record) return errorResponse(404, "找不到這個產品");
  const body = await readBody(init);
  const factType = formValue(body, "fact_type");
  record.facts.push({
    id: nextId("pfact"),
    fact_type: factType,
    fact_type_label: label(PRODUCT_FACT_TYPES, factType),
    label: formValue(body, "label"),
    value: formValue(body, "value"),
    status: formValue(body, "status") === "confirmed" ? "confirmed" : "pending",
    confirmed_by: null,
    confirmed_at: null,
    source_reference: formValue(body, "source_reference") || null,
  });
  return noContent();
});

registerRoute(
  "POST",
  /^\/api\/products\/brands\/[^/]+\/products\/([^/]+)\/facts\/([^/]+)$/,
  async (match, init) => {
    const record = findProduct(match[1]);
    const fact = record?.facts.find((f) => f.id === match[2]);
    if (!record || !fact) return errorResponse(404, "找不到這條事實");
    const body = await readBody(init);
    const factType = formValue(body, "fact_type");
    fact.fact_type = factType;
    fact.fact_type_label = label(PRODUCT_FACT_TYPES, factType);
    fact.label = formValue(body, "label");
    fact.value = formValue(body, "value");
    fact.source_reference = formValue(body, "source_reference") || null;
    return noContent();
  },
);

registerRoute(
  "POST",
  /^\/api\/products\/brands\/[^/]+\/products\/([^/]+)\/facts\/([^/]+)\/confirm$/,
  async (match, init) => {
    const record = findProduct(match[1]);
    const fact = record?.facts.find((f) => f.id === match[2]);
    if (!record || !fact) return errorResponse(404, "找不到這條事實");
    const body = await readBody(init);
    fact.status = "confirmed";
    fact.confirmed_by = formValue(body, "confirmed_by");
    fact.confirmed_at = new Date().toISOString();
    return noContent();
  },
);

registerRoute("POST", /^\/api\/products\/brands\/[^/]+\/products\/([^/]+)\/facts\/([^/]+)\/delete$/, (match) => {
  const record = findProduct(match[1]);
  if (!record) return errorResponse(404, "找不到這個產品");
  record.facts = record.facts.filter((f) => f.id !== match[2]);
  return noContent();
});

// ---- 產品經濟數字 ----

registerRoute(
  "POST",
  /^\/api\/products\/brands\/[^/]+\/products\/([^/]+)\/economics$/,
  async (match, init) => {
    const record = findProduct(match[1]);
    if (!record) return errorResponse(404, "找不到這個產品");
    const body = await readBody(init);
    const num = (key: string) => {
      const v = body[key];
      return typeof v === "number" ? v : Number(v) || 0;
    };
    record.economics = {
      selling_price: num("selling_price"),
      fixed_cost: num("fixed_cost"),
      unit_variable_cost: num("unit_variable_cost"),
      shipping_cost: num("shipping_cost"),
      currency: formValue(body, "currency") || "TWD",
      cpa_roas_basis: formValue(body, "cpa_roas_basis") || null,
      effective_from: formValue(body, "effective_from") || null,
      status: "confirmed",
      confirmed_by: formValue(body, "confirmed_by"),
    };
    return noContent();
  },
);

registerRoute("POST", /^\/api\/products\/brands\/[^/]+\/products\/([^/]+)\/economics\/confirm$/, (match) => {
  const record = findProduct(match[1]);
  if (!record?.economics) return errorResponse(404, "找不到這個產品的經濟數字");
  record.economics.status = "confirmed";
  record.economics.confirmed_by = record.economics.confirmed_by ?? "AI 快掃資料，人工確認無誤";
  return noContent();
});

// ---- 調研交接包 ----

registerRoute("GET", /^\/api\/products\/brands\/[^/]+\/products\/([^/]+)\/handoff$/, (match) => {
  const record = findProduct(match[1]);
  if (!record) return errorResponse(404, "找不到這個產品");
  const promptText =
    `你是產品研究助理，請幫我針對「${record.name}」這個產品，整理出：核心資訊、作用機制、` +
    `差異化、使用情境、目標客群、視覺風格，各 1 到 3 條，並在最後附上你參考的網址。` +
    `請用「類型：內容」一行一條的格式回覆，方便我直接貼回系統解析。`;
  return jsonResponse(envelope({ prompt_text: promptText }));
});

registerRoute(
  "POST",
  /^\/api\/products\/brands\/[^/]+\/products\/([^/]+)\/handoff$/,
  async (match, init) => {
    const record = findProduct(match[1]);
    if (!record) return errorResponse(404, "找不到這個產品");
    const body = await readBody(init);
    const replyText = formValue(body, "reply_text").trim();
    if (!replyText) return errorResponse(400, "請先把外部 AI 的回覆貼進來。");
    if (getActionFailure()) {
      return errorResponse(400, budgetExceededMessage("請 AI 幫忙整理格式", COST_PRODUCT_HANDOFF_FIX));
    }
    const addedCount = 2;
    for (let i = 0; i < addedCount; i++) {
      const factType = PRODUCT_FACT_TYPES[i % PRODUCT_FACT_TYPES.length][0];
      record.facts.push({
        id: nextId("pfact"),
        fact_type: factType,
        fact_type_label: label(PRODUCT_FACT_TYPES, factType),
        label: `深研交接包新增：${label(PRODUCT_FACT_TYPES, factType)}`,
        value: replyText.slice(0, 80),
        status: "pending",
        confirmed_by: null,
        confirmed_at: null,
        source_reference: "深研交接包貼回",
      });
    }
    return jsonResponse({ added_count: addedCount });
  },
  { skipAutoFail: true },
);

// ---- 永久刪除產品 ----

registerRoute("GET", /^\/api\/products\/brands\/[^/]+\/products\/([^/]+)\/delete$/, (match) => {
  const record = findProduct(match[1]);
  if (!record) return errorResponse(404, "找不到這個產品");
  return jsonResponse(envelope(productDeleteImpact(match[1])));
});

registerRoute(
  "POST",
  /^\/api\/products\/brands\/[^/]+\/products\/([^/]+)\/delete$/,
  async (match, init) => {
    const record = findProduct(match[1]);
    if (!record) return errorResponse(404, "找不到這個產品");
    const body = await readBody(init);
    if (formValue(body, "confirm_name") !== record.name) {
      return errorResponse(400, "輸入的名稱跟產品名稱不一樣，請照著上面顯示的名稱再打一次。");
    }
    const idx = productsStore.findIndex((r) => r.id === record.id);
    if (idx >= 0) productsStore.splice(idx, 1);
    return noContent();
  },
);
