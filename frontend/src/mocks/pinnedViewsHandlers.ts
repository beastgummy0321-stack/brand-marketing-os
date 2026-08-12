/** 駕駛艙成效釘選區路由表（票 B4R-cockpit-pins）。只攔 `pinned-views`／`performance-view`
 * 兩個新路徑，不影響駕駛艙其餘已接真後端的 `/api/dashboard/brands/{id}/cockpit`（沒對到的
 * 路徑一律放行給真正的 fetch，見 `network.ts`）。 */
import { PINNED_VIEW_LIMIT, type PinnedViewKey } from "@/lib/pinnedViewsApi";
import { buildPerformanceView, getPinnedViews, PINNED_VIEW_CATALOG, setPinnedViews } from "./pinnedViewsData";
import { envelope, errorResponse, jsonResponse, registerRoute } from "./network";

const VALID_KEYS = new Set(PINNED_VIEW_CATALOG.map((c) => c.key));

async function readBody(init?: RequestInit): Promise<Record<string, unknown>> {
  if (!init?.body) return {};
  try {
    return JSON.parse(String(init.body)) as Record<string, unknown>;
  } catch {
    return {};
  }
}

// ---- S3P.1-3：目錄＋目前釘選清單 ----

registerRoute("GET", /^\/api\/dashboard\/brands\/([^/]+)\/pinned-views$/, (match) => {
  const brandId = match[1];
  return jsonResponse(envelope({ catalog: PINNED_VIEW_CATALOG, pinned: getPinnedViews(brandId) }));
});

// ---- S3P.4：勾選變更即刻送出 ----

registerRoute("POST", /^\/api\/dashboard\/brands\/([^/]+)\/pinned-views$/, async (match, init) => {
  const brandId = match[1];
  const body = await readBody(init);
  const views = Array.isArray(body.views) ? (body.views as unknown[]) : null;
  if (!views || !views.every((v): v is PinnedViewKey => typeof v === "string" && VALID_KEYS.has(v as PinnedViewKey))) {
    return errorResponse(400, "釘選清單格式不對。");
  }
  if (views.length > PINNED_VIEW_LIMIT) {
    return errorResponse(400, `最多只能釘選 ${PINNED_VIEW_LIMIT} 個視圖，先取消一個才能再選。`);
  }
  setPinnedViews(brandId, views as PinnedViewKey[]);
  return jsonResponse(envelope({ catalog: PINNED_VIEW_CATALOG, pinned: getPinnedViews(brandId) }));
});

// ---- S3P.5-13：各視圖內容 ----

registerRoute("GET", /^\/api\/dashboard\/brands\/[^/]+\/performance-view\/([^/]+)$/, (match) => {
  const key = match[1] as PinnedViewKey;
  if (!VALID_KEYS.has(key)) return errorResponse(404, "沒有這個視圖。");
  return jsonResponse(envelope(buildPerformanceView(key)));
});
