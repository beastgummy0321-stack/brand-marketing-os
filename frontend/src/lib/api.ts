/** 儀表板 API 型別與呼叫（票 02-overview-cards）。
 * 對應 app/dashboard/routes.py 的統一回應信封：{ data, generated_at }。 */

import { apiFetch } from "./http";

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
  const res = await apiFetch("/api/dashboard/overview");
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
  stage: "遠期備戰" | "中期備戰" | "近期備戰";
  days_until: number;
}

export interface CockpitData {
  brand_id: string;
  brand_name: string;
  /** 'YYYY-MM'：月報卡數字所屬的月份（票 F5）。 */
  month: string;
  /** 月報卡的期間／口徑說明，後端組好的成句（票 F5，例：「期間：2026 年 8 月
   * （當月至今）｜口徑：…」）——前端原樣顯示，不自己組字避免口徑跟後端算法兜不攏。 */
  basis_note: string;
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
  /** 最後一次成效同步時間（票 07-auto-sync）：Meta 快照抓取時間／GA4 同步時間取
   * 較新者；從沒同步過是 null。`data_stale`＝從沒同步過，或最後一次同步不是今天。 */
  last_sync_at: string | null;
  data_stale: boolean;
}

/** SOL R6-2：單一品牌的立刻更新入口，駕駛艙與作戰室共用。 */
export interface ImmediateSyncResult {
  updated_at: string;
}

export async function triggerImmediateSync(brandId: string): Promise<ImmediateSyncResult> {
  const res = await apiFetch("/api/dashboard/brands/" + encodeURIComponent(brandId) + "/sync", { method: "POST" });
  if (!res.ok) {
    let message = "更新失敗（狀態碼 " + res.status + "）";
    try {
      const body = (await res.json()) as { error?: string };
      if (body.error) message = body.error;
    } catch {
      // 回應不是 JSON，用預設訊息。
    }
    throw new Error(message);
  }
  const body = (await res.json()) as { data?: { updated_at?: string; synced_at?: string; last_sync_at?: string }; updated_at?: string; synced_at?: string; last_sync_at?: string };
  const data = body.data ?? body;
  const updatedAt = data.updated_at ?? data.synced_at ?? data.last_sync_at;
  if (!updatedAt) throw new Error("更新完成，但伺服器沒有回傳更新時間。");
  return { updated_at: updatedAt };
}
export async function fetchCockpit(brandId: string): Promise<CockpitData> {
  const res = await apiFetch(`/api/dashboard/brands/${encodeURIComponent(brandId)}/cockpit`);
  if (!res.ok) {
    throw new Error(
      res.status === 404 ? "找不到這個品牌。" : `儀表板 API 回應異常（狀態碼 ${res.status}）`,
    );
  }
  const body: Envelope<CockpitData> = await res.json();
  return body.data;
}

/** 一鍵「知道了」：使用 SPA 專用 JSON 端點，避免 fetch 跟隨舊 Jinja 的 PRG 轉址。 */
export async function resolveAlert(interruptId: string): Promise<void> {
  const res = await apiFetch(`/api/interrupts/${encodeURIComponent(interruptId)}/resolve`, {
    method: "POST",
  });
  if (!res.ok) {
    throw new Error(`「知道了」失敗（狀態碼 ${res.status}）`);
  }
}
