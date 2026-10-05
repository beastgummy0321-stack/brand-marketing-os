/** 儀表板 API 型別與呼叫（票 02-overview-cards）。
 * 對應 app/dashboard/routes.py 的統一回應信封：{ data, generated_at }。
 *
 * 外殼切片（2026-08-28）：駕駛艙（`fetchCockpit`）、立刻更新（`triggerImmediateSync`）
 * 與它們的型別隨 `app/ads/` 一起刪掉——那些欄位全部是廣告成效數字。這支檔案現在只剩
 * 跨品牌總覽與警示「知道了」兩件事。 */

import { apiFetch, throwIfFailed } from "./http";

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
  await throwIfFailed(res, `儀表板 API 回應異常（狀態碼 ${res.status}）`);
  const body: Envelope<DashboardBrandCard[]> = await res.json();
  return body.data;
}

/** F50-I17：總覽「已封存的品牌」摺疊區——這個組織封存了的品牌（依名稱排序）。 */
export interface ArchivedBrand {
  brand_id: string;
  name: string;
}

export async function fetchArchivedBrands(): Promise<ArchivedBrand[]> {
  const res = await apiFetch("/api/dashboard/archived-brands");
  await throwIfFailed(res, `讀不到已封存的品牌（狀態碼 ${res.status}）`);
  const body: Envelope<ArchivedBrand[]> = await res.json();
  return body.data;
}

/** 票 06：品牌頁本月花費／營收／毛利／ROAS 併桌。對應 app/dashboard/repository.py
 * `brand_month_money()`。revenue／margin／roas 為 null 一律代表「沒得算」（鐵則 16），
 * 不是 0。票 12：revenue 是全通路加總（官網、平台商店、實體店…），margin 仍然只有官網
 * ——只有官網訂單有品項與成本，見 CockpitPage.tsx MonthMoneySection 檔頭說明。 */
export interface BrandMonthMoney {
  spend: number;
  revenue: number | null;
  margin: number | null;
  /** 有營收但沒登記單位成本的 SKU 數——毛利算不出來時，畫面用這個數字講清楚原因。 */
  margin_unknown_sku_count: number;
  roas: number | null;
  /** 這個品牌本月以外是不是曾經有過任何訂單；false＝空態，不是零收入。 */
  has_orders: boolean;
  /** 這段區間內是否有任何平台商店（marketplace）通路的營收列——蝦皮等平台的欄位對照
   * 還沒拿真實匯出檔驗證過，true 時畫面要繼續提醒這部分數字還不能全信。 */
  marketplace_uncalibrated: boolean;
}

export async function fetchBrandMonth(brandId: string): Promise<BrandMonthMoney> {
  const res = await apiFetch(`/api/dashboard/brands/${encodeURIComponent(brandId)}/month`);
  await throwIfFailed(res, `本月營收讀取失敗（狀態碼 ${res.status}）`);
  const body: Envelope<BrandMonthMoney> = await res.json();
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
  await throwIfFailed(res, `「知道了」失敗（狀態碼 ${res.status}）`);
}
