/** 檔期規劃 API 型別與呼叫（票 07：最薄路徑）。對應 `app/schedule/routes.py`。
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

export interface SchedulePlan {
  task_id: string;
  created_at: string;
  product_ids: string[];
  daily_budget: number;
  narrative: string;
  splits: ScheduleSplit[];
  failure: string | null;
}

export interface ScheduleState {
  daily_budget: number;
  plan: SchedulePlan | null;
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
  productIds: string[],
): Promise<ScheduleState> {
  const res = await apiFetch(`/api/schedule/brands/${encodeURIComponent(brandId)}/plans`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ product_ids: productIds }),
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
