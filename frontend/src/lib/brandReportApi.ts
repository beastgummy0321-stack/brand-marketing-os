import { apiFetch, readJson } from "./http";

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

export async function fetchBrandReport(brandId: string): Promise<BrandReportResponse> {
  const res = await apiFetch(base(brandId));
  return readJson<BrandReportResponse>(res, "報告讀取失敗");
}

export async function generateBrandReport(brandId: string): Promise<void> {
  const res = await apiFetch(`${base(brandId)}/generate`, { method: "POST" });
  await readJson(res, "報告生成失敗");
}
