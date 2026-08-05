/** 儀表板 API 型別與呼叫（票 02-overview-cards）。
 * 對應 app/dashboard/routes.py 的統一回應信封：{ data, generated_at }。 */

export interface ActiveCycle {
  id: string;
  status: string;
  status_label: string;
}

export interface DashboardBrandCard {
  brand_id: string;
  brand_name: string;
  health: "red" | "yellow" | "green";
  revenue_this_month: number | null;
  revenue_mom_pct: number | null;
  active_cycle: ActiveCycle | null;
  /** 本票先留位，04-guide-card-engine 接上真貨源。 */
  next_step: string | null;
}

interface Envelope<T> {
  data: T;
  generated_at: string;
}

export async function fetchOverview(): Promise<DashboardBrandCard[]> {
  const res = await fetch("/api/dashboard/overview");
  if (!res.ok) {
    throw new Error(`儀表板 API 回應異常（狀態碼 ${res.status}）`);
  }
  const body: Envelope<DashboardBrandCard[]> = await res.json();
  return body.data;
}

/** 單一 KPI：本期值＋環比（與上月同期比較）＋迷你趨勢線（票 03-cockpit-kpi-chart）。
 * `value`／`trend` 內的 `null`＝「沒得算」（例如這個月完全沒收到成效資料），
 * 不是 0（鐵則 16）——畫面要能分辨「沒資料」跟「資料是 0」。 */
export interface CockpitKpi {
  value: number | null;
  mom_pct: number | null;
  trend: (number | null)[];
}

export interface CockpitData {
  brand_id: string;
  brand_name: string;
  kpis: {
    revenue: CockpitKpi;
    spend: CockpitKpi;
    roas: CockpitKpi;
    orders: CockpitKpi;
  };
  chart: {
    months: string[];
    revenue: (number | null)[];
    spend: (number | null)[];
  };
}

export async function fetchCockpit(brandId: string): Promise<CockpitData> {
  const res = await fetch(`/api/dashboard/brands/${encodeURIComponent(brandId)}/cockpit`);
  if (!res.ok) {
    throw new Error(
      res.status === 404 ? "找不到這個品牌。" : `儀表板 API 回應異常（狀態碼 ${res.status}）`,
    );
  }
  const body: Envelope<CockpitData> = await res.json();
  return body.data;
}
