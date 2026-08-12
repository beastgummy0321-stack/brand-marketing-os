/** 路由表（票 B4-campaigns）：契約「要新增的 API」節列的端點在這裡登記，`mocks/index.tsx`
 * import 這個檔案把路由掛進 `network.ts` 的攔截器。 */
import { INTERVIEW_AXES, cycleLabel, type InterviewSelection } from "@/lib/campaignsApi";
import { bucketOf, campaignsStore, findCampaign, toListItem } from "./campaignsData";
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

// ---- 檔期清單（S7.2-S7.7）----

registerRoute("GET", /^\/api\/campaigns\/brands\/[^/]+$/, () => {
  const list = getScenario() === "empty" ? [] : campaignsStore.map(toListItem);
  return jsonResponse(envelope(list));
});

// ---- 封存／恢復（S7.4，同一顆開關）----

registerRoute("POST", /^\/api\/campaigns\/brands\/[^/]+\/([^/]+)\/archive$/, (match) => {
  const record = findCampaign(match[1]);
  if (!record) return errorResponse(404, "找不到這期檔期");
  record.archived = !record.archived;
  return noContent();
});

// ---- 永久刪除（S7.9-S7.13）----

registerRoute("GET", /^\/api\/campaigns\/brands\/[^/]+\/([^/]+)\/delete-impact$/, (match) => {
  const record = findCampaign(match[1]);
  if (!record) return errorResponse(404, "找不到這期檔期");
  return jsonResponse(envelope(record.deleteImpact));
});

registerRoute("POST", /^\/api\/campaigns\/brands\/[^/]+\/([^/]+)\/delete$/, async (match, init) => {
  const record = findCampaign(match[1]);
  if (!record) return errorResponse(404, "找不到這期檔期");
  if (bucketOf(record) !== "archived") {
    return errorResponse(400, "要先把檔期封存，才能永久刪除。");
  }
  const body = await readBody(init);
  const confirmName = typeof body.confirm_name === "string" ? body.confirm_name.trim() : "";
  if (confirmName !== cycleLabel(record)) {
    return errorResponse(400, "輸入的檔期名稱跟上面顯示的不一樣，請照著再打一次。");
  }
  const index = campaignsStore.indexOf(record);
  if (index >= 0) campaignsStore.splice(index, 1);
  return noContent();
});

// ---- 前朝教訓訪談（S7.14-S7.19）----
// 同一軸值兩邊都勾＝矛盾，兩邊都不採納，邏輯逐字對照 `app/ads/interview.py _drop_conflicts()`
// （查證日 2026-08-12）：不替使用者挑一邊，誠實告知哪幾項沒記。

registerRoute("POST", /^\/api\/campaigns\/brands\/[^/]+\/interview$/, async (_match, init) => {
  const body = (await readBody(init)) as unknown as InterviewSelection;
  const bad = { ...(body.bad ?? {}) };
  const good = { ...(body.good ?? {}) };
  const conflicts: string[] = [];

  for (const axis of INTERVIEW_AXES) {
    const badValues = bad[axis.key] ?? [];
    const goodValues = good[axis.key] ?? [];
    const overlap = badValues.filter((v) => goodValues.includes(v));
    if (overlap.length === 0) continue;
    bad[axis.key] = badValues.filter((v) => !overlap.includes(v));
    good[axis.key] = goodValues.filter((v) => !overlap.includes(v));
    for (const value of overlap) {
      const valueLabel = axis.values.find((o) => o.value === value)?.label ?? value;
      conflicts.push(`${axis.label}的「${valueLabel}」`);
    }
  }

  const ruleCardCount = Object.values(bad).reduce((sum, values) => sum + (values?.length ?? 0), 0);
  const hypothesisCount = Object.values(good).reduce((sum, values) => sum + (values?.length ?? 0), 0);

  return jsonResponse({ rule_card_count: ruleCardCount, hypothesis_count: hypothesisCount, conflicts });
});
