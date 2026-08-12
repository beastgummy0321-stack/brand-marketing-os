/** 駕駛艙成效釘選區假資料（票 B4R-cockpit-pins，契約 `.scratch/grill/GRILL-B4R-performance.md`
 * 第一節）。4 個真實視圖共用「這個品牌目前的檔期」（契約：沿用 `_latest_cycle()` 精神，取
 * 最新一期未封存檔期）——原型選既有 `campaignsStore` 裡的 LIVE 檔期（`cyc-5`），跟 S8 作戰室
 * 的健康燈號／成效訊息假資料是同一筆（`warroomPerformanceData.ts`），不重複造第二品牌
 * （契約「醜資料」節）。貼文留位視圖（S3P.7）恆定不查資料，跟有沒有檔期無關。 */
import {
  type AdOverviewView,
  type AttributionView,
  type DashboardPerformanceView,
  type HealthLightsView,
  type PinnedViewCatalogItem,
  type PinnedViewKey,
  type WeeklyBurnView,
} from "@/lib/pinnedViewsApi";
import { campaignsStore, type CampaignRecord } from "./campaignsData";
import { getScenario } from "./state";
import { buildAttributionSummary, buildHealthLights, buildPerformanceSummary, buildReadingResult } from "./warroomPerformanceData";

/** 首發目錄（契約 R3-1，5 筆固定）：剛好等於釘選上限，首次進駕駛艙全部預設釘選（S3P 版型骨架）。 */
export const PINNED_VIEW_CATALOG: PinnedViewCatalogItem[] = [
  { key: "ad_overview", label: "廣告總覽" },
  { key: "post_placeholder", label: "貼文（短影音）" },
  { key: "weekly_burn", label: "本週燒錢與進度" },
  { key: "attribution", label: "訂單歸因" },
  { key: "health_lights", label: "檔期健康燈號" },
];

/** 品牌層釘選設定（對應 `app_setting` 鍵 `dashboard_pinned_views:{brand_id}`）。未存過的品牌
 * 讀不到＝目錄全部預設釘選（S3P 版型骨架「首次進駕駛艙」）。 */
const pinnedByBrand = new Map<string, PinnedViewKey[]>();

export function getPinnedViews(brandId: string): PinnedViewKey[] {
  return pinnedByBrand.get(brandId) ?? PINNED_VIEW_CATALOG.map((c) => c.key);
}

export function setPinnedViews(brandId: string, views: PinnedViewKey[]): void {
  pinnedByBrand.set(brandId, views);
}

/** 「這個品牌目前的檔期」：優先取進行中投放（LIVE），沒有就取最新一期未封存、未結案的
 * 檔期，兩者都沒有＝這個品牌還沒開過檔期（S3P.13）。`empty` 開發情境固定沒有檔期。 */
export function getCurrentCycleRecord(): CampaignRecord | null {
  if (getScenario() === "empty") return null;
  const live = campaignsStore.find((r) => r.status === "LIVE" && !r.archived);
  if (live) return live;
  const inProgress = campaignsStore
    .filter((r) => !r.archived && r.status !== "CLOSED")
    .sort((a, b) => (a.start_date < b.start_date ? 1 : -1));
  return inProgress[0] ?? null;
}

function buildWeeklyBurn(record: CampaignRecord): WeeklyBurnView {
  // 原型沒有逐日花費追蹤資料表，只有 cyc-5（現行「目前檔期」示範用）備了跟健康燈號
  // 燒錢速度一致的敘事數字（55% 天數／76% 預算，overspend）；其餘記錄誠實顯示樣本不足
  // （鐵則 16：沒有底層資料就不假裝算得出來）。
  if (record.id === "cyc-5") {
    return { kind: "weekly_burn", cycle_id: record.id, status: "overspend", time_progress: 0.55, budget_progress: 0.76, days_left: record.days_left ?? 0 };
  }
  return { kind: "weekly_burn", cycle_id: record.id, status: "insufficient_sample", time_progress: null, budget_progress: null, days_left: record.days_left ?? 0 };
}

function buildAdOverview(record: CampaignRecord): AdOverviewView {
  const summary = buildPerformanceSummary(record) ?? {
    spend: 0, impressions: 0, reach: 0, clicks: 0, conversions: 0, revenue: 0,
    kpis: { ctr: null, cpc: null, cpa: null, roas: null }, discarded_rows: 0,
  };
  return { kind: "ad_overview", cycle_id: record.id, summary, reading_status: buildReadingResult(record)?.status ?? null };
}

function buildAttribution(record: CampaignRecord): AttributionView {
  const a = buildAttributionSummary(buildPerformanceSummary(record));
  return { kind: "attribution", cycle_id: record.id, gross: a.gross, net: a.net, excluded: a.excluded, natural: a.natural };
}

function buildHealthLightsView(record: CampaignRecord): HealthLightsView {
  const h = buildHealthLights(record);
  return { kind: "health_lights", cycle_id: record.id, spend_rate: h.spend_rate, cpa: h.cpa, roas: h.roas, fatigue: h.fatigue };
}

export function buildPerformanceView(key: PinnedViewKey): DashboardPerformanceView | null {
  if (key === "post_placeholder") return { kind: "post_placeholder" }; // S3P.7：恆定空態，不查資料
  const record = getCurrentCycleRecord();
  if (!record) return null; // S3P.13：這個品牌還沒開過任何檔期
  if (key === "ad_overview") return buildAdOverview(record);
  if (key === "weekly_burn") return buildWeeklyBurn(record);
  if (key === "attribution") return buildAttribution(record);
  return buildHealthLightsView(record);
}
