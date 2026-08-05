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
