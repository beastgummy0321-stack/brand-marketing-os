/** S8 檔期作戰室路由表（票 B4-warroom）。掛在跟 S7 同一個 `installMockFetch()` 攔截器，
 * `mocks/index.tsx` import 這個檔案即可生效。GET 的具名子路徑（`new-context`／
 * `ai-cost-meter`）必須排在通用「檔期詳情」`GET /{brand}/{cycle}` 之前註冊——攔截器
 * 用陣列順序找第一個符合的路由，具名路徑不先擋住就會被通用兩段式路徑誤吃。 */
import { findCampaign } from "./campaignsData";
import {
  buildAccountStructure,
  buildCycle,
  buildDissents,
  buildPlanOptions,
  buildRuleCardsLearned,
  buildSliderOptions,
  deriveStage,
  NEW_CYCLE_OBJECTIVES,
  NEW_CYCLE_PRODUCTS,
} from "./warroomPlanData";
import {
  buildAutoChecks,
  buildChecklist,
  buildCodes,
  buildNamingCheck,
  buildPackages,
  buildUtmCheck,
} from "./warroomHandoffData";
import { AI_COST_METER, buildCheckpoint, buildClosingReview, buildPerformanceSummary, buildReadingResult } from "./warroomPerformanceData";
import { envelope, errorResponse, jsonResponse, registerRoute } from "./network";
import { getScenario } from "./state";

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

// ---- 開檔（S8.1-11）----

registerRoute("GET", /^\/api\/campaigns\/[^/]+\/new-context$/, () => {
  const empty = getScenario() === "empty";
  return jsonResponse(
    envelope({
      offer_simulation: empty, // 品牌一期都沒跑過時才問（契約 S8.1）
      products: empty ? [] : NEW_CYCLE_PRODUCTS,
      slider_options: buildSliderOptions(),
      duration_config: { min: 7, max: 30, min_daily_budget: 300 },
      objectives: NEW_CYCLE_OBJECTIVES,
      recommended_objective: "sales",
      readiness_notes: ["這個品牌的商品到達頁還沒有掛 Pixel 轉換事件，開檔前建議先確認（不會擋你送出）。"],
    }),
  );
});

registerRoute("POST", /^\/api\/campaigns\/([^/]+)$/, async (_match, init) => {
  const body = await readBody(init);
  const override = typeof body.budget_override === "number" ? body.budget_override : null;
  if (override !== null && override <= 0) {
    return errorResponse(400, "預算金額不能是 0 或負數，請重新輸入。");
  }
  // 原型簡化：不動態生一整套新檔期資料，一律導向既有 PLANNING 示範檔期（cyc-1）
  // 繼續往下走企劃步驟（跳過了什麼：見交付報告）。
  return jsonResponse({ cycle_id: "cyc-1", message: "檔期已建立，接下來確認這期的計畫。" });
});

registerRoute("POST", /^\/api\/campaigns\/[^/]+\/target-cpa-guided$/, async (_match, init) => {
  const body = await readBody(init);
  const events = Number(body.events_per_sale) || 1;
  const margin = Number(body.margin_per_sale) || 0;
  return jsonResponse({ value: Math.round((margin / events) * 100) / 100 });
});

// ---- 右欄 AI 花費儀表（跟 B3 同一份品牌層數字）----

registerRoute("GET", /^\/api\/campaigns\/([^/]+)\/ai-cost-meter$/, (match) => {
  return jsonResponse(envelope({ brand_id: match[1], ...AI_COST_METER, settings_url: "/settings" }));
});

// ---- 檔期完整狀態＋封存 ----

registerRoute("GET", /^\/api\/campaigns\/([^/]+)\/([^/]+)$/, (match) => {
  const record = findCampaign(match[2]);
  if (!record) return errorResponse(404, "找不到這期檔期");
  return jsonResponse(envelope({ cycle: buildCycle(record), stage: deriveStage(record), readiness_notes: [] }));
});

registerRoute("POST", /^\/api\/campaigns\/([^/]+)\/([^/]+)\/archive$/, (match) => {
  const record = findCampaign(match[2]);
  if (!record) return errorResponse(404, "找不到這期檔期");
  record.archived = !record.archived;
  return noContent();
});

// ---- 企劃（S8.12-22）----

registerRoute("POST", /^\/api\/campaigns\/([^/]+)\/([^/]+)\/plan\/generate$/, (match) => {
  const record = findCampaign(match[2]);
  if (record && record.status === "PLANNING") record.status = "PLAN_SELECT";
  return noContent();
});
registerRoute("GET", /^\/api\/campaigns\/[^/]+\/[^/]+\/plan\/status$/, () => jsonResponse(envelope({ status: "done" })));

registerRoute("GET", /^\/api\/campaigns\/[^/]+\/([^/]+)\/plan\/options$/, (match) => {
  const record = findCampaign(match[1]);
  if (!record) return errorResponse(404, "找不到這期檔期");
  return jsonResponse(
    envelope({ options: buildPlanOptions(record), account_structure: buildAccountStructure(record), dissents: buildDissents(record) }),
  );
});

registerRoute("POST", /^\/api\/campaigns\/([^/]+)\/([^/]+)\/plan\/select$/, (match) => {
  const record = findCampaign(match[2]);
  if (record) record.status = "REVIEW";
  return noContent();
});
registerRoute("POST", /^\/api\/campaigns\/[^/]+\/[^/]+\/dissents\/[^/]+\/decide$/, () => noContent());
registerRoute("POST", /^\/api\/campaigns\/([^/]+)\/([^/]+)\/plan\/approve$/, (match) => {
  const record = findCampaign(match[2]);
  if (record) record.status = "PRODUCTION";
  return noContent();
});
registerRoute("POST", /^\/api\/campaigns\/[^/]+\/[^/]+\/pacing$/, () => noContent());

registerRoute("GET", /^\/api\/campaigns\/[^/]+\/([^/]+)\/rule-cards-learned$/, (match) => {
  const record = findCampaign(match[1]);
  return jsonResponse(envelope(record ? buildRuleCardsLearned(record) : []));
});

// ---- 交接（S8.25-46）----

registerRoute("GET", /^\/api\/campaigns\/[^/]+\/([^/]+)\/checklist$/, (match) => {
  const record = findCampaign(match[1]);
  if (!record) return errorResponse(404, "找不到這期檔期");
  return jsonResponse(envelope(buildChecklist(record)));
});
registerRoute("POST", /^\/api\/campaigns\/[^/]+\/[^/]+\/checklist\/[^/]+\/[^/]+$/, () => noContent());
registerRoute("POST", /^\/api\/campaigns\/[^/]+\/[^/]+\/handoff\/qa-launch\/[^/]+$/, () => noContent());

registerRoute("GET", /^\/api\/campaigns\/[^/]+\/([^/]+)\/handoff\/qa-auto-check$/, (match) => {
  const record = findCampaign(match[1]);
  if (!record) return errorResponse(404, "找不到這期檔期");
  return jsonResponse(envelope(buildAutoChecks(record)));
});

registerRoute("GET", /^\/api\/campaigns\/[^/]+\/([^/]+)\/handoff\/naming-check$/, (match) => {
  const record = findCampaign(match[1]);
  if (!record) return errorResponse(404, "找不到這期檔期");
  const packages = buildPackages(record);
  return jsonResponse(envelope({ naming: buildNamingCheck(packages), utm: buildUtmCheck(packages) }));
});

registerRoute("GET", /^\/api\/campaigns\/[^/]+\/([^/]+)\/handoff$/, (match) => {
  const record = findCampaign(match[1]);
  if (!record) return errorResponse(404, "找不到這期檔期");
  const { codes, mismatches } = buildCodes(record);
  return jsonResponse(
    envelope({ packages: buildPackages(record), codes, codes_verify_mismatch: mismatches, account_structure: buildAccountStructure(record) }),
  );
});

registerRoute("POST", /^\/api\/campaigns\/[^/]+\/[^/]+\/handoff\/build$/, () => noContent());
registerRoute("POST", /^\/api\/campaigns\/[^/]+\/[^/]+\/handoff\/codes$/, () => noContent());
registerRoute("POST", /^\/api\/campaigns\/([^/]+)\/([^/]+)\/handoff\/codes\/verify$/, (match) => {
  const record = findCampaign(match[2]);
  const { mismatches } = record ? buildCodes(record) : { mismatches: null };
  return jsonResponse({ mismatches: mismatches ?? [] });
});
registerRoute("POST", /^\/api\/campaigns\/[^/]+\/[^/]+\/handoff\/[^/]+\/activate$/, () => noContent());

// ---- 期中檢查點（S8.47-50）----

registerRoute("GET", /^\/api\/campaigns\/[^/]+\/([^/]+)\/checkpoint\/(day3|day7)$/, (match) => {
  const record = findCampaign(match[1]);
  if (!record) return errorResponse(404, "找不到這期檔期");
  return jsonResponse(envelope(buildCheckpoint(record, match[2] as "day3" | "day7")));
});

// ---- 成效（S8.51-58）----

registerRoute("GET", /^\/api\/campaigns\/[^/]+\/([^/]+)\/performance$/, (match) => {
  const record = findCampaign(match[1]);
  if (!record) return errorResponse(404, "找不到這期檔期");
  return jsonResponse(
    envelope({ summary: buildPerformanceSummary(record), reading: buildReadingResult(record), confidence_label: "尚未完成對帳三題自答，可信度中等" }),
  );
});
registerRoute("POST", /^\/api\/campaigns\/[^/]+\/[^/]+\/performance\/simulate$/, () => noContent());

// ---- 覆盤（S8.59-66）----

registerRoute("GET", /^\/api\/campaigns\/[^/]+\/([^/]+)\/closing-review$/, (match) => {
  const record = findCampaign(match[1]);
  if (!record) return errorResponse(404, "找不到這期檔期");
  const review = buildClosingReview(record);
  if (!review) return errorResponse(400, "這期還沒結案，覆盤要等成效判讀跑完期末結算才會出現。");
  return jsonResponse(envelope(review));
});
