export interface OnboardingItem {
  key: string;
  label: string;
  optional: boolean;
  status: "not_started" | "in_progress" | "done";
  has_data: boolean;
  badge_label: string;
  badge_kind: "neutral" | "warn" | "ok";
  description: string;
  action_text: string;
  action_url: string;
  baseline: [string, string, boolean][] | null;
  baseline_note: string | null;
  hint: string | null;
}

export interface OnboardingJob {
  status: "idle" | "running" | "done" | "failed";
  stage?: string;
  started_at?: string;
  message?: string;
}

export interface DataOnboardingResponse {
  data: {
    checklist: OnboardingItem[];
    progress: { done: number; total: number; next_item: OnboardingItem | null; all_done: boolean };
    maturity: {
      rows: { label: string; value_label: string; threshold_label: string; met: boolean; gap: string | null }[];
      all_met: boolean;
    };
    jobs: { meta_backfill: OnboardingJob; ga4_backfill: OnboardingJob; ga4_sync: OnboardingJob };
  };
  generated_at: string;
}

function base(brandId: string): string {
  return `/api/campaigns/brands/${encodeURIComponent(brandId)}`;
}

async function errorMessage(res: Response): Promise<string> {
  const body = await res.json().catch(() => null);
  return typeof body?.detail === "string" ? body.detail : `操作失敗（狀態碼 ${res.status}）`;
}

export async function fetchDataOnboarding(brandId: string): Promise<DataOnboardingResponse> {
  const res = await fetch(`${base(brandId)}/data-onboarding`);
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export async function startMetaBackfill(brandId: string): Promise<void> {
  const res = await fetch(`${base(brandId)}/backfill/meta`, { method: "POST" });
  if (!res.ok) throw new Error(await errorMessage(res));
}

export async function startGa4Backfill(brandId: string): Promise<void> {
  const res = await fetch(`${base(brandId)}/backfill/ga4`, { method: "POST" });
  if (!res.ok) throw new Error(await errorMessage(res));
}

export async function startGa4Sync(brandId: string): Promise<void> {
  const res = await fetch(`${base(brandId)}/sync/ga4`, { method: "POST" });
  if (!res.ok) throw new Error(await errorMessage(res));
}
