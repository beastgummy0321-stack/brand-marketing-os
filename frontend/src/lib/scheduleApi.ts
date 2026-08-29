/** 檔期規劃 API 型別與呼叫（票 07：最薄路徑；票 08：表單加平台／目標／促銷重點／方案數，
 * 一次回 N 個方案）。對應 `app/schedule/routes.py`。
 * 這支端點不用 `{data, generated_at}` 信封（見 `lib/api.ts` 的 `Envelope<T>`）——
 * 票 07 settled 段「API — 字面契約」直接寫死回應形狀，這裡逐欄對照，不套用別支
 * feature 的信封慣例。 */
import { apiFetch } from "./http";

export interface ScheduleSplit {
  label: string;
  share: number;
  why: string;
  daily_amount: number;
}

export interface SchedulePlanItem {
  summary: string;
  reasoning: string;
  splits: ScheduleSplit[];
}

export interface ScheduleSource {
  title: string;
  url: string;
}

export interface SchedulePlan {
  task_id: string;
  created_at: string;
  product_ids: string[];
  daily_budget: number;
  platform: string;
  objective: string;
  promotion_note: string;
  narrative: string;
  plans: SchedulePlanItem[];
  sources: ScheduleSource[];
  failure: string | null;
}

/** 平台／行銷目標選項——內容全部來自 `app/schedule/platform_objectives.json`，前端只轉譯
 * 成畫面，不自己寫死任何平台或目標的中文字（票 08：CONTEXT.md 的三詞界線）。 */
export interface SchedulePlatformOption {
  id: string;
  label: string;
  enabled: boolean;
}

export interface ScheduleObjectiveOption {
  platform: string;
  value: string;
  label: string;
  source_url: string;
  verified_date: string;
}

export interface ScheduleState {
  daily_budget: number;
  plan_count_min: number;
  plan_count_max: number;
  platforms: SchedulePlatformOption[];
  objectives: ScheduleObjectiveOption[];
  plan: SchedulePlan | null;
}

export interface CreateSchedulePlanInput {
  productIds: string[];
  platform: string;
  objective: string;
  promotionNote: string;
  planCount: number;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await apiFetch(path);
  if (!res.ok) {
    throw new Error(res.status === 404 ? "找不到這個品牌。" : `讀取失敗（狀態碼 ${res.status}）`);
  }
  return (await res.json()) as T;
}

export function fetchSchedule(brandId: string): Promise<ScheduleState> {
  return getJson(`/api/schedule/brands/${encodeURIComponent(brandId)}`);
}

export async function createSchedulePlan(
  brandId: string,
  input: CreateSchedulePlanInput,
): Promise<ScheduleState> {
  const res = await apiFetch(`/api/schedule/brands/${encodeURIComponent(brandId)}/plans`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      product_ids: input.productIds,
      platform: input.platform,
      objective: input.objective,
      promotion_note: input.promotionNote,
      plan_count: input.planCount,
    }),
  });
  if (!res.ok) {
    let message = `排程失敗（狀態碼 ${res.status}）`;
    try {
      const data = (await res.json()) as { error?: { message?: string } };
      if (data.error?.message) message = data.error.message;
    } catch {
      // 回應不是 JSON，用預設訊息。
    }
    throw new Error(message);
  }
  return (await res.json()) as ScheduleState;
}
