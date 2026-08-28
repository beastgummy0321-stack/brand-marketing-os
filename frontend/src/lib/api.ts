/** 儀表板 API 型別與呼叫（票 02-overview-cards）。
 * 對應 app/dashboard/routes.py 的統一回應信封：{ data, generated_at }。
 *
 * 外殼切片（2026-08-28）：駕駛艙（`fetchCockpit`）、立刻更新（`triggerImmediateSync`）
 * 與它們的型別隨 `app/ads/` 一起刪掉——那些欄位全部是廣告成效數字。這支檔案現在只剩
 * 跨品牌總覽與警示「知道了」兩件事。 */

import { apiFetch } from "./http";

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

/** 打斷佇列的嚴重度（app/core/interrupts.py SEVERITY_ORDER）。收件匣與
 * `lib/severity.ts` 的顏色／文字對照共用這個型別；駕駛艙的警示區已隨 `app/ads/`
 * 刪掉，但打斷佇列本身還在。 */
export type AlertSeverity = "money_loss" | "irreversible" | "rule_warning" | "informational";

/** 一鍵「知道了」：使用 SPA 專用 JSON 端點，避免 fetch 跟隨舊 Jinja 的 PRG 轉址。 */
export async function resolveAlert(interruptId: string): Promise<void> {
  const res = await apiFetch(`/api/interrupts/${encodeURIComponent(interruptId)}/resolve`, {
    method: "POST",
  });
  if (!res.ok) {
    throw new Error(`「知道了」失敗（狀態碼 ${res.status}）`);
  }
}
