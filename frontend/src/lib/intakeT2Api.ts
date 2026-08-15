/** T2 真相卡／人物誌 API。信封拆解與錯誤處理照 trackingApi.ts；不混進舊逐條確認路徑。 */
import type { IntakeReviewItem } from "./intakeApi";

export type TruthCardBucket = "accepted" | "needs_confirmation" | "forbidden";
export type TruthAnswerKind = "price" | "claim_permission" | null;

export interface TruthCardItem extends Omit<IntakeReviewItem, "dup_hint" | "severity"> {
  outcome: "pending" | "confirmed" | "pending_saved" | "discarded";
  status: string;
  landed: boolean;
  landed_pending: boolean;
  answer_kind: TruthAnswerKind;
}

export interface TruthCard {
  accepted: TruthCardItem[];
  needs_confirmation: TruthCardItem[];
  forbidden: TruthCardItem[];
}

export interface Persona {
  id: string;
  brand_id: string;
  title: string;
  when_needed: string;
  care_about: string;
  hesitation: string;
  where_to_find: string;
  created_at: string;
}

export interface PersonaGeneration {
  status: "idle" | "running" | "done" | "failed";
  stage: string;
  started_at: string | null;
  usual_range_text: string;
  error: string | null;
}

export interface PersonaBundle {
  personas: Persona[];
  generation: PersonaGeneration;
}

interface Envelope<T> {
  data: T;
  generated_at: string;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(res.status === 404 ? "找不到這筆資料。" : `讀取失敗（狀態碼 ${res.status}）`);
  const body: Envelope<T> = await res.json();
  return body.data;
}

async function postJson<T = void>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok) {
    let message = `處理失敗（狀態碼 ${res.status}）`;
    try {
      const data = (await res.json()) as { error?: string };
      if (data.error) message = data.error;
    } catch {
      // 非 JSON 回應就沿用白話預設錯誤。
    }
    throw new Error(message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const base = (brandId: string) => `/api/intake/brands/${encodeURIComponent(brandId)}`;

export const fetchTruthCard = (brandId: string): Promise<TruthCard> => getJson(`${base(brandId)}/truth-card`);

export const confirmTruthCard = (
  brandId: string,
  answers: Record<string, { value?: string; decision?: "can_say" | "cannot_say" }>,
): Promise<void> => postJson(`${base(brandId)}/truth-card/confirm`, { answers });

export const moveTruthCardItem = (brandId: string, index: number, target: TruthCardBucket): Promise<void> =>
  postJson(`${base(brandId)}/truth-card/items/${encodeURIComponent(index)}/move`, { target });

export const fetchPersonas = (brandId: string): Promise<PersonaBundle> => getJson(`${base(brandId)}/personas`);

/** 後端 202 回傳 {generation}，在 API 邊界直接拆開，元件不碰傳輸包裝。 */
export const regeneratePersonas = (brandId: string): Promise<PersonaGeneration> =>
  postJson<{ generation: PersonaGeneration }>(`${base(brandId)}/personas/regenerate`).then((body) => body.generation);
