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

async function errorMessage(res: Response): Promise<string> {
  const body = await res.json().catch(() => null);
  return typeof body?.detail === "string" ? body.detail : `操作失敗（狀態碼 ${res.status}）`;
}

export async function fetchBrandReport(brandId: string): Promise<BrandReportResponse> {
  const res = await fetch(base(brandId));
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export async function generateBrandReport(brandId: string): Promise<void> {
  const res = await fetch(`${base(brandId)}/generate`, { method: "POST" });
  if (!res.ok) throw new Error(await errorMessage(res));
}
