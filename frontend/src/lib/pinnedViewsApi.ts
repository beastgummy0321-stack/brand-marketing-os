/** 駕駛艙成效釘選區 API 型別與呼叫（票 B4R-cockpit-pins，契約
 * `.scratch/grill/GRILL-B4R-performance.md` 第一節）。型別逐字對照契約「假資料 TS 型別」節，
 * `HealthLight`／`HealthLightStatus` 跟作戰室健康燈號共用同一份定義（`lib/warroomApi.ts`），
 * 不重複兩套判定型別（契約 S3P.12／S8R.20「共用」註記）。 */
import type { HealthLight, HealthLightStatus, PerformanceSummary, ReadingResult } from "./warroomApi";

export type { HealthLight, HealthLightStatus };

export type PinnedViewKey = "ad_overview" | "post_placeholder" | "weekly_burn" | "attribution" | "health_lights";

/** 最多釘選 5 個視圖（契約 R2-1 定案）。 */
export const PINNED_VIEW_LIMIT = 5;

export interface PinnedViewCatalogItem {
  key: PinnedViewKey;
  label: string;
}

export interface PinnedViewsConfig {
  catalog: PinnedViewCatalogItem[];
  pinned: PinnedViewKey[];
}

export interface AdOverviewView {
  kind: "ad_overview";
  cycle_id: string;
  summary: PerformanceSummary;
  reading_status: ReadingResult["status"] | null;
  last_synced_at?: string | null;
  /** B0-15：這個檔期的日期區間，「看這期完整作戰室」連結旁要標出來是哪一期。 */
  cycle_label: string;
}

export interface PostPlaceholderView {
  kind: "post_placeholder";
}

export interface WeeklyBurnView {
  kind: "weekly_burn";
  cycle_id: string;
  status: "normal" | "overspend" | "underspend" | "insufficient_sample";
  time_progress: number | null;
  budget_progress: number | null;
  days_left: number;
}

export interface AttributionView {
  kind: "attribution";
  cycle_id: string;
  gross: { count: number; net_revenue: number };
  net: { count: number; net_revenue: number };
  excluded: { count: number; net_revenue: number };
  natural: { count: number; net_revenue: number };
}

export interface HealthLightsView {
  kind: "health_lights";
  cycle_id: string;
  spend_rate: HealthLight;
  cpa: HealthLight;
  roas: HealthLight;
  fatigue: HealthLight;
}

export type DashboardPerformanceView =
  | AdOverviewView
  | PostPlaceholderView
  | WeeklyBurnView
  | AttributionView
  | HealthLightsView;

interface Envelope<T> {
  data: T;
  generated_at: string;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) {
    throw new Error(res.status === 404 ? "找不到這筆資料。" : `讀取失敗（狀態碼 ${res.status}）`);
  }
  const body: Envelope<T> = await res.json();
  return body.data;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let message = `處理失敗（狀態碼 ${res.status}）`;
    try {
      const data = (await res.json()) as { error?: string };
      if (data.error) message = data.error;
    } catch {
      // 回應不是 JSON，用預設訊息。
    }
    throw new Error(message);
  }
  const body2: Envelope<T> = await res.json();
  return body2.data;
}

const base = (brandId: string) => `/api/dashboard/brands/${encodeURIComponent(brandId)}`;

export const fetchPinnedViews = (brandId: string): Promise<PinnedViewsConfig> =>
  getJson(`${base(brandId)}/pinned-views`);

/** 送出使用者目前勾選的視圖清單（≤5），成功回傳更新後的設定（S3P.4：chips 列即時更新）。 */
export const savePinnedViews = (brandId: string, views: PinnedViewKey[]): Promise<PinnedViewsConfig> =>
  postJson(`${base(brandId)}/pinned-views`, { views });

/** `null`＝這個品牌完全沒開過任何檔期（S3P.13，貼文留位視圖除外，恆定顯示不查資料）。 */
export const fetchPerformanceView = (
  brandId: string,
  viewKey: PinnedViewKey,
): Promise<DashboardPerformanceView | null> => getJson(`${base(brandId)}/performance-view/${viewKey}`);
