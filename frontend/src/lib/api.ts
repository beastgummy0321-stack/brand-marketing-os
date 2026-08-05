/** 儀表板 API 型別與呼叫（票 02-overview-cards）。
 * 對應 app/dashboard/routes.py 的統一回應信封：{ data, generated_at }。 */

export interface ActiveCycle {
  id: string;
  status: string;
  status_label: string;
}

/** 下一步指南卡（票 04-guide-card-engine）：一件事＋一鍵前往。
 * 對應 app/dashboard/guide_cards.py build() 的輸出形狀。 */
export interface GuideCard {
  title: string;
  action_url: string;
}

export interface DashboardBrandCard {
  brand_id: string;
  brand_name: string;
  health: "red" | "yellow" | "green";
  revenue_this_month: number | null;
  revenue_mom_pct: number | null;
  active_cycle: ActiveCycle | null;
  /** 指南卡引擎排序後的第一筆；沒有待辦是 null（畫面顯示「一切正常」）。 */
  next_step: GuideCard | null;
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

/** 異常警示區（票 05-alerts-fuel-pipeline）：直接讀打斷佇列，已按嚴重度排序
 * （money_loss ＞ irreversible ＞ rule_warning ＞ informational，見
 * app/core/interrupts.py SEVERITY_ORDER）。action_url 為 null＝沒有「詳情」可去。 */
export type AlertSeverity = "money_loss" | "irreversible" | "rule_warning" | "informational";

export interface Alert {
  id: string;
  severity: AlertSeverity;
  message: string;
  action_url: string | null;
}

/** AI 油錢錶（票 05）：本月已花（llm_task 成本紀錄）／全站共用花費上限（設定頁可調）。 */
export interface FuelGauge {
  spent_this_month: number;
  limit: number;
}

/** 內容產線小計（票 05）：待審（DRAFT）／已發（APPROVED）素材則數。 */
export interface ContentPipeline {
  pending: number;
  published: number;
}

/** 檔期日曆第一層（票 06-campaign-calendar）：進行中檔期目前處於三階段中的哪一段。
 * 對應 app/dashboard/campaign_calendar.py current_campaign_stage() 的輸出形狀。 */
export interface CampaignStage {
  id: string;
  name: string;
  tier: "large" | "medium" | "small";
  tier_label: string;
  stage: "預熱" | "高潮" | "衝刺";
  days_until: number;
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
  /** 常駐下一步指南卡（票 04-guide-card-engine）：最多 3 件，優先序排列；
   * 空陣列＝一切正常。 */
  guide_cards: GuideCard[];
  /** 沒有檔期在提前期窗口內是 null。 */
  campaign_stage: CampaignStage | null;
  alerts: Alert[];
  fuel_gauge: FuelGauge;
  content_pipeline: ContentPipeline;
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

/** 一鍵「知道了」：沿用既有全站打斷佇列 resolve 端點（app/brand_intelligence/routes.py
 * `/interrupts/{id}/resolve`，非 `/api/dashboard` 之下——那支路由本來就不寫在儀表板
 * 模組，不重寫、不搬家）。該端點是舊版伺服器渲染流程的 PRG 轉址，fetch 預設會
 * 跟著轉址走完，最後拿到的是（跟這次呼叫無關的）HTML；只要 `res.ok` 就代表成功。 */
export async function resolveAlert(interruptId: string): Promise<void> {
  const res = await fetch(`/interrupts/${encodeURIComponent(interruptId)}/resolve`, {
    method: "POST",
  });
  if (!res.ok) {
    throw new Error(`「知道了」失敗（狀態碼 ${res.status}）`);
  }
}
