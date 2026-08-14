/** T1 本週作戰 API；所有成功與失敗回應都先拆 {data, generated_at} 信封。 */

export type WeeklyGrade = "save" | "spend" | "asset";
export type WeeklyRejudgeStatus = "running" | "done" | "failed";

export interface SpendConfirmation {
  required: true;
  suggested_amount: number | null;
  currency: "TWD";
}

export interface WeeklyProposal {
  id: string;
  action: string;
  target: string;
  reason: string;
  impact: string;
  instruction: string;
  status: "GENERATED" | "ACCEPTED" | "APPLIED";
  grade: WeeklyGrade;
  copy: string;
  spend_confirmation: SpendConfirmation | null;
  action_card: string | null;
  action_url: string | null;
}

export interface WeeklyProposalsData {
  cycle_id: string | null;
  proposals: WeeklyProposal[];
  execution_checklist: WeeklyProposal[];
}

export interface WeeklyApproveData extends WeeklyProposalsData {
  approved: WeeklyProposal;
}

export interface WeeklyApproveAllData extends WeeklyProposalsData {
  approved: WeeklyProposal[];
  pending_confirmation: WeeklyProposal[];
}

export interface WeeklySkipData extends WeeklyProposalsData {
  skipped_id: string;
}

export interface WeeklyRejudgeState {
  status: WeeklyRejudgeStatus;
  message?: string;
}

interface Envelope<T> {
  data: T;
  generated_at: string;
}

async function requestData<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  let body: Envelope<T> | null = null;
  try {
    body = (await response.json()) as Envelope<T>;
  } catch {
    // 非 JSON 回應由下方共用訊息處理。
  }
  if (!response.ok) {
    const errorData = body?.data as { error?: string } | undefined;
    throw new Error(errorData?.error ?? `處理失敗（狀態碼 ${response.status}）`);
  }
  if (!body) throw new Error("伺服器回應格式不正確。");
  return body.data;
}

const base = (brandId: string) =>
  `/api/campaigns/brands/${encodeURIComponent(brandId)}/weekly`;

const post = <T>(path: string, body: unknown = {}): Promise<T> =>
  requestData<T>(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });

export const fetchWeeklyProposals = (brandId: string): Promise<WeeklyProposalsData> =>
  requestData(`${base(brandId)}/proposals`);

export const approveWeeklyProposal = (
  brandId: string,
  proposalId: string,
  confirmedAmount?: number,
): Promise<WeeklyApproveData> =>
  post(`${base(brandId)}/proposals/${encodeURIComponent(proposalId)}/approve`,
    confirmedAmount === undefined ? {} : { confirmed_amount: confirmedAmount });

export const skipWeeklyProposal = (
  brandId: string,
  proposalId: string,
): Promise<WeeklySkipData> =>
  post(`${base(brandId)}/proposals/${encodeURIComponent(proposalId)}/skip`);

export const approveAllWeeklyProposals = (brandId: string): Promise<WeeklyApproveAllData> =>
  post(`${base(brandId)}/proposals/approve-all`);

export const startWeeklyRejudge = (brandId: string): Promise<WeeklyRejudgeState> =>
  post(`${base(brandId)}/rejudge`);

export const fetchWeeklyRejudgeStatus = (brandId: string): Promise<WeeklyRejudgeState> =>
  requestData(`${base(brandId)}/rejudge/status`);
