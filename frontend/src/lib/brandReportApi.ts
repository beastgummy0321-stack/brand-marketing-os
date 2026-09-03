import { apiFetch, errorMessageFromResponse } from "./http";

export interface BrandReportSection {
  label: string;
  summary: string;
  points: string[];
}

export interface BrandReport {
  generated_at: string;
  brand_version: number;
  model: string;
  source_fact_count: number;
  cost: number | null;
  staleness: string | null;
  thin_data: boolean;
  sections: BrandReportSection[];
}

export type BrandReportJob =
  | { status: "idle" }
  | { status: "running"; stage: string; started_at: string }
  | { status: "failed"; message: string };

export interface BrandReportResponse {
  report: BrandReport | null;
  job: BrandReportJob;
}

function base(brandId: string): string {
  return `/api/brands/${encodeURIComponent(brandId)}/report`;
}

/** 走 `http.ts` 那支共用的三種外殼解析（票 07-3）。這裡原本自己刻了一份只認 `detail` 的
 * 版本，碰到 `web.ApiError` 的 `{"error": {"code","message"}}` 外殼就退回 fallback——
 * identity 路由的 401 會顯示「操作失敗（狀態碼 401）」而不是「請先登入」。2026-08-29 修
 * `[object Object]` 那次把五個 api 檔改成共用這支，這個檔跟 `ordersApi.ts` 是漏掉的兩個。 */
async function errorMessage(res: Response): Promise<string> {
  return errorMessageFromResponse(res, `操作失敗（狀態碼 ${res.status}）`);
}

export async function fetchBrandReport(brandId: string): Promise<BrandReportResponse> {
  const res = await apiFetch(base(brandId));
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export async function generateBrandReport(brandId: string): Promise<void> {
  const res = await apiFetch(`${base(brandId)}/generate`, { method: "POST" });
  if (!res.ok) throw new Error(await errorMessage(res));
}
