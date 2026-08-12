/** S8 作戰室「交接／投放前檢查」假資料（票 B4-warroom）。checklist 三份清單的 label／help
 * 逐字抄 `app/ads/checklist.py:28-92`（查證日 2026-08-12）——這是後端已定版的固定文案，
 * 前端原型照抄，不是自己命名。 */
import type { AutoCheckResult, ChecklistItem, CodeAssignment, HandoffPackage, NamingCheckResult, UtmCheckResult } from "@/lib/warroomApi";
import type { CampaignRecord } from "./campaignsData";

// app/ads/checklist.py:28-37
const ONE_TIME_ITEMS = [
  { key: "pixel_confirmed", label: "Pixel 已安裝並確認轉換事件正常觸發", help: "去 Meta 事件管理工具確認 Pixel 有裝在網站上，且轉換事件（例如購買）有正常觸發。確認過一次以後這裡會記住，之後不用每期重新勾——除非系統看到「花了錢卻零轉換」這種異常訊號。" },
];
// app/ads/checklist.py:39-52
const CYCLE_ITEMS = [
  { key: "landing_page_consistent", label: "到達頁的訊息跟這期廣告一致", help: "廣告在講的優惠、賣點、產品，跟消費者點進去看到的到達頁對得起來，不要「掛羊頭賣狗肉」。" },
  { key: "budget_matches_structure", label: "帳戶預算配置照這期的規則卡底案設定", help: "在 Meta 廣告管理員設定的 CBO／ABO 結構與各組日預算，跟系統算出的底案一致（交接包裡有寫）。" },
  { key: "red_flag_scan_reviewed", label: "已看過紅線詞掃描結果", help: "素材那一步的紅線詞掃描只抓得到明確字詞，抓不到語氣語意——正式投放前自己再看一眼有沒有法規風險字眼。" },
];
// app/ads/checklist.py:61-92
export const QA_LAUNCH_ITEMS = [
  { key: "qa_pixel_installed", label: "Pixel 已正確安裝" },
  { key: "qa_audience_exclusion", label: "受眾排除名單已設定" },
  { key: "qa_capi_emq_quality", label: "CAPI／EMQ 事件品質已確認" },
  { key: "qa_budget_line_review", label: "預算已逐筆覆核" },
  { key: "qa_landing_page_click_test", label: "到達頁已實點測試" },
];

/** 交接包尚未建置的檔期（cyc-4）checklist 全部未勾——契約「四態」空狀態列點：
 * 「素材/交接包/檢查清單至少一個檔期涵蓋全部空狀態」。 */
export function buildChecklist(record: CampaignRecord): ChecklistItem[] {
  const allUnchecked = record.id === "cyc-4";
  const items: ChecklistItem[] = ONE_TIME_ITEMS.map((it) => ({ ...it, checked: !allUnchecked, checked_by: allUnchecked ? null : "系統示範帳號", hint: null }));
  items.push(
    ...CYCLE_ITEMS.map((it, i) => ({
      ...it,
      checked: !allUnchecked && i !== 2,
      checked_by: !allUnchecked && i !== 2 ? "系統示範帳號" : null,
      hint: it.key === "red_flag_scan_reviewed" ? "目前掃到 2 處命中" : null,
    })),
  );
  return items;
}

/** QA 系統覆核五項：涵蓋「已覆核通過」「未過」「無法覆核」三態（契約「假資料要包含」節）。
 * ②③兩項 available=false——目前 `meta_api.py` 讀不到受眾排除名單與 EMQ 分數（契約「拿不準的
 * 點」第 1 點，屬既有整合範圍外，不是本票能自己判斷技術上做不做得到）。 */
export function buildAutoChecks(record: CampaignRecord): AutoCheckResult[] {
  const pixelOk = record.id !== "cyc-5"; // cyc-5 示範「未過」：花了錢卻零轉換的異常訊號
  return [
    { key: "qa_pixel_installed", label: "Pixel 已正確安裝", available: true, passed: pixelOk, note: pixelOk ? "近期投放有正常收到轉換事件。" : "近期已花費但零轉換，Pixel 可能異常，建議重新確認安裝。" },
    { key: "qa_audience_exclusion", label: "受眾排除名單已設定", available: false, passed: null, note: "Meta Marketing API 目前的整合範圍讀不到自訂受眾排除設定，維持自行確認。" },
    { key: "qa_capi_emq_quality", label: "CAPI／EMQ 事件品質已確認", available: false, passed: null, note: "EMQ 分數屬 Events Manager 專屬頁面數據，非標準 insights 欄位，目前讀不到，維持自行確認。" },
    { key: "qa_budget_line_review", label: "預算已逐筆覆核", available: true, passed: record.id !== "cyc-5", note: record.id === "cyc-5" ? "有一組廣告組的 Meta 實際日預算跟底案不一致，請人工核對。" : "各組 Meta 實際日預算與底案相符。" },
    { key: "qa_landing_page_click_test", label: "到達頁已實點測試", available: true, passed: true, note: "系統已對每組到達網址送出一次輕量探測，回應碼皆為 2xx。內容正不正確還是要自己看一眼。" },
  ];
}

const LONG_NAME_SUFFIX = "_限時優惠加碼再加碼超級無敵長版本測試命名不會截斷或爆版確認欄位";

export function buildPackages(record: CampaignRecord): HandoffPackage[] {
  if (record.id === "cyc-4") return []; // 契約「四態」空狀態：交接包尚未產生
  const angleCode = record.id === "cyc-5" ? "warm_scene" : "warm_pain";
  const base: HandoffPackage[] = [
    {
      id: `${record.id}-pkg-1`,
      campaign_name: `demo_${record.start_date}_${record.objective}_a1${record.id === "cyc-5" ? LONG_NAME_SUFFIX : ""}`,
      adset_name: `${angleCode}_01`,
      ad_name: `${angleCode}_01_ad`,
      objective_label: "銷售",
      daily_budget: Math.round(record.budget / 14),
      schedule_text: "全天投放，不分時段",
      hook_text: "退貨率降了，因為我們沒有再誇大",
      copy_text: "持續使用搭配均衡飲食，感受看得見的變化。",
      full_url: "https://example-demo-brand.test/products/collagen?utm_source=meta&utm_medium=cpc&utm_campaign=demo&utm_content=a1",
      image_prompts: ["溫暖居家情境，手拿產品瓶身特寫"],
      mapping: record.id === "cyc-5" ? { meta_campaign_id: "1234567890", confirmed_by: "系統示範帳號", confirmed_at: `${record.start_date}T10:00:00+08:00` } : null,
    },
    {
      id: `${record.id}-pkg-2`,
      campaign_name: record.id === "cyc-5" ? `demo_${record.start_date}_${record.objective}_a1${LONG_NAME_SUFFIX}` : `demo_${record.start_date}_${record.objective}_a2`,
      adset_name: `${angleCode}_02`,
      ad_name: `${angleCode}_02_ad`,
      objective_label: "銷售",
      daily_budget: Math.round(record.budget / 14),
      schedule_text: "全天投放，不分時段",
      hook_text: "真人使用心得分享",
      copy_text: null,
      full_url: "https://example-demo-brand.test/products/collagen",
      image_prompts: ["產品使用情境短影片首格"],
      mapping: null,
    },
  ];
  return base;
}

export function buildNamingCheck(packages: HandoffPackage[]): NamingCheckResult {
  const seen = new Map<string, string[]>();
  for (const pkg of packages) {
    const key = `campaign_name:${pkg.campaign_name}`;
    seen.set(key, [...(seen.get(key) ?? []), pkg.id]);
  }
  const duplicates = [...seen.entries()]
    .filter(([, ids]) => ids.length > 1)
    .map(([key, ids]) => ({ field: key.split(":")[0] as "campaign_name", value: key.split(":")[1], package_ids: ids }));
  const missing = packages.filter((p) => !p.ad_name).map((p) => ({ package_id: p.id, field: "ad_name" }));
  return { duplicates, missing, passed: duplicates.length === 0 && missing.length === 0 };
}

/** UTM 四參數存在檢查＋官方標準第 5 個經典參數 `utm_term` 標「不適用」（不是缺漏）——
 * 來源：Google Analytics 官方說明 support.google.com/analytics/answer/10917952
 * （查證日 2026-08-12）。Meta 是興趣／受眾投放不是關鍵字搜尋廣告，沒有對應概念可填。 */
export function buildUtmCheck(packages: HandoffPackage[]): UtmCheckResult[] {
  return packages.map((pkg, i) => {
    const present = i === 0 ? ["utm_source", "utm_medium", "utm_campaign", "utm_content"] : ["utm_source", "utm_medium", "utm_campaign"];
    return {
      package_id: pkg.id,
      present,
      not_applicable: [{ param: "utm_term", reason: "Meta 是興趣／受眾投放，沒有對應「付費關鍵字」概念，不算缺漏。" }],
      passed: present.length === 4,
    };
  });
}

export function buildCodes(record: CampaignRecord): { codes: CodeAssignment[]; mismatches: string[] | null } {
  if (record.id === "cyc-4") return { codes: [], mismatches: null };
  const codes: CodeAssignment[] = [
    { kind: "ad", kind_label: "廣告碼", code: `AD${record.id.toUpperCase()}`, discount_pct: 15, usage_cap: 200, valid_until: record.end_date },
    { kind: "voiceover", kind_label: "口播碼", code: `VO${record.id.toUpperCase()}`, discount_pct: 10, usage_cap: 100, valid_until: record.end_date },
  ];
  const mismatches = record.id === "cyc-5" ? ["廣告碼折數在 EasyStore 後台設定為 10%，跟系統配碼的 15% 不符"] : null;
  return { codes, mismatches };
}
