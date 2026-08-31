/** 開帳讀歷史（票 S2）API 型別與呼叫。對應 `app/schedule/onboarding_routes.py` /
 * `app/schedule/onboarding.py`，型別逐欄照抄後端實際回應（S2-DESIGN.md D13——若設計文件跟
 * 已出貨的後端不一致，以後端為準，這裡就是照後端寫的）。
 *
 * 沿用 `scheduleApi.ts` 的既有寫法：GET 用 `getJson`（`:174-184`），POST 用
 * try/catch＋`errorMessageFrom`（`:261-278`），一律經 `apiFetch`，不 import
 * `@supabase/supabase-js`。 */
import { apiFetch, errorMessageFrom } from "./http";

export interface OnboardingBoundAccount {
  id: string;
  account_id: string;
  name: string;
}

/** 回不出素材的廣告——票 S2 §1：絕不整筆消失，這裡連名字一起帶著顯示。 */
export interface OnboardingUnreadableAd {
  ad_id: string;
  name: string;
}

/** Meta 列得出來、但這段期間一列數字都沒有的活動——同一條規矩（報出來，不是靜靜跳過）。 */
export interface OnboardingSkippedCampaign {
  campaign_id: string;
  name: string;
}

/** `scope` 是 `"brand"` 或某個產品 id；`scope_label` 是後端已經轉譯好的中文顯示字，畫面
 * 不用知道 `scope` 本身代表什麼。`acceptable: false` 時 `scope_note` 才會出現（D9：代理
 * 回報的範圍猜不到是品牌還是哪個產品，畫面只能顯示原因、不能自己猜）。 */
export interface OnboardingConclusion {
  index: number;
  text: string;
  scope: string;
  scope_label: string;
  confidence: string;
  evidence: string;
  sample_note: string;
  acceptable: boolean;
  accepted: boolean;
  scope_note?: string;
}

export interface OnboardingJob {
  task_id: string;
  campaign_id: string;
  campaign_name: string;
  status: string;
  failure: string | null;
  running: boolean;
  unreadable_ads: OnboardingUnreadableAd[];
  conclusions: OnboardingConclusion[];
}

export interface OnboardingReadWindow {
  since: string;
  until: string;
}

export interface OnboardingRead {
  read_id: string;
  started_at: string;
  window: OnboardingReadWindow | null;
  attribution_windows: string[];
  days_without_data: string[];
  coverage_note: string;
  campaigns_note: string;
  /** Meta 列得出來、但這段期間手上一列數字都沒有，因此沒有派分析員讀的活動。 */
  campaigns_without_numbers: OnboardingSkippedCampaign[];
  expected: number;
  succeeded: number;
  finished: boolean;
  jobs: OnboardingJob[];
}

export interface OnboardingReadState {
  bound_accounts: OnboardingBoundAccount[];
  read: OnboardingRead | null;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await apiFetch(path);
  if (!res.ok) {
    throw new Error(res.status === 404 ? "找不到這個品牌。" : `讀取失敗（狀態碼 ${res.status}）`);
  }
  return (await res.json()) as T;
}

export function fetchOnboardingRead(brandId: string): Promise<OnboardingReadState> {
  return getJson(`/api/schedule/brands/${encodeURIComponent(brandId)}/onboarding-read`);
}

export async function startOnboardingRead(brandId: string): Promise<OnboardingReadState> {
  const res = await apiFetch(`/api/schedule/brands/${encodeURIComponent(brandId)}/onboarding-read`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!res.ok) {
    let message = `開始讀取失敗（狀態碼 ${res.status}）`;
    try {
      const data = (await res.json()) as { error?: { message?: string } };
      message = errorMessageFrom(data, message);
    } catch {
      // 回應不是 JSON，用預設訊息。
    }
    throw new Error(message);
  }
  return (await res.json()) as OnboardingReadState;
}

export async function acceptOnboardingConclusions(
  brandId: string,
  taskId: string,
  indexes: number[],
): Promise<OnboardingReadState> {
  const res = await apiFetch(
    `/api/schedule/brands/${encodeURIComponent(brandId)}/onboarding-read/accept`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ task_id: taskId, indexes }),
    },
  );
  if (!res.ok) {
    let message = `採用失敗（狀態碼 ${res.status}）`;
    try {
      const data = (await res.json()) as { error?: { message?: string } };
      message = errorMessageFrom(data, message);
    } catch {
      // 回應不是 JSON，用預設訊息。
    }
    throw new Error(message);
  }
  return (await res.json()) as OnboardingReadState;
}
