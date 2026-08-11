/** 路由表（票 B1-inbox／B1-settings）：契約列出的每個端點在這裡登記一筆，import 這個檔案
 * 就會把全部路由掛進 `network.ts` 的攔截器（副作用 import，見 `mocks/index.tsx`）。 */
import {
  BRAND_OPTIONS,
  BRAND_OPTIONS_EMPTY,
  buildDashboardOverview,
  buildRuleCardsData,
  buildSettingsData,
  INBOX_EMPTY,
  INBOX_NORMAL,
  PROTOTYPE_PHASE_DETAIL,
  resetRuleCardValues,
  saveRuleCardValues,
} from "./data";
import { envelope, jsonResponse, registerRoute } from "./network";
import { getApiKeySource, getScenario, setApiKeySource } from "./state";

// ---- 收件匣（S2）----

registerRoute("GET", /^\/api\/inbox$/, () =>
  jsonResponse(envelope(getScenario() === "empty" ? INBOX_EMPTY : INBOX_NORMAL)),
);

registerRoute("GET", /^\/api\/system\/prototype-phase$/, () =>
  jsonResponse(envelope(PROTOTYPE_PHASE_DETAIL)),
);

// 沿用既有全站 resolve 端點（見 lib/api.ts resolveAlert 註解）：前端只認 res.ok，body 內容
// 不重要。
registerRoute("POST", /^\/interrupts\/[^/]+\/resolve$/, () => new Response(null, { status: 200 }));

// ---- 設定（S15）----

registerRoute("GET", /^\/api\/settings$/, () => jsonResponse(envelope(buildSettingsData(getApiKeySource()))));

registerRoute("POST", /^\/api\/settings\/meta$/, () => jsonResponse({}));
registerRoute("POST", /^\/api\/settings\/ga4$/, () => jsonResponse({}));
registerRoute("POST", /^\/api\/settings\/api-key$/, () => {
  setApiKeySource("db");
  return jsonResponse({});
});
registerRoute("POST", /^\/api\/settings\/api-key\/clear-db$/, () => {
  setApiKeySource(null);
  return jsonResponse({});
});
registerRoute("POST", /^\/api\/settings\/model$/, () => jsonResponse({}));
registerRoute("POST", /^\/api\/settings\/creative-root$/, () => jsonResponse({}));
registerRoute("POST", /^\/api\/settings\/prompt-header$/, () => jsonResponse({}));
registerRoute("POST", /^\/api\/settings\/budget$/, () => jsonResponse({}));

registerRoute("GET", /^\/api\/settings\/rule-cards\/brands\/([^/]+)$/, (match) =>
  jsonResponse(envelope(buildRuleCardsData(decodeURIComponent(match[1])))),
);

registerRoute(
  "POST",
  /^\/api\/settings\/rule-cards\/brands\/[^/]+\/([^/]+)$/,
  async (match, init) => {
    const cardKey = decodeURIComponent(match[1]);
    const fields: Record<string, number> = init?.body ? JSON.parse(String(init.body)) : {};
    return jsonResponse(envelope(saveRuleCardValues(cardKey, fields)));
  },
);

registerRoute(
  "POST",
  /^\/api\/settings\/rule-cards\/brands\/[^/]+\/([^/]+)\/reset$/,
  (match) => jsonResponse(envelope(resetRuleCardValues(decodeURIComponent(match[1])))),
);

// 品牌選擇器沿用既有跨品牌總覽端點（契約「不用新增」節）。這裡攔截它是畫面契約第 1 段
// 「零後端」的臨時措施，只在 mocks/ 有裝載時生效，stage 2 拿掉這個目錄後這支端點會
// 直接打回真後端，不用改前端呼叫端一行程式碼。
registerRoute("GET", /^\/api\/dashboard\/overview$/, () => {
  const brands = getScenario() === "empty" ? BRAND_OPTIONS_EMPTY : BRAND_OPTIONS;
  return jsonResponse(envelope(buildDashboardOverview(brands)));
});
