/** 人物誌 API（圖書館 `PersonaSection` 讀它）。信封拆解與錯誤處理照 trackingApi.ts。
 * F42-I14 拆掉了這裡原本的真相卡呼叫。 */
import { apiFetch, errorMessageFrom } from "./http";

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
  const res = await apiFetch(path);
  if (!res.ok) throw new Error(res.status === 404 ? "找不到這筆資料。" : `讀取失敗（狀態碼 ${res.status}）`);
  const body: Envelope<T> = await res.json();
  return body.data;
}

async function postJson<T = void>(path: string, body?: unknown): Promise<T> {
  const res = await apiFetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok) {
    let message = `處理失敗（狀態碼 ${res.status}）`;
    try {
      const data = (await res.json()) as { error?: string };
      message = errorMessageFrom(data, message);
    } catch {
      // 非 JSON 回應就沿用白話預設錯誤。
    }
    throw new Error(message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

async function putJson(path: string, body: unknown): Promise<void> {
  const res = await apiFetch(path, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let message = `儲存失敗（狀態碼 ${res.status}）`;
    try {
      const data = (await res.json()) as { error?: string };
      message = errorMessageFrom(data, message);
    } catch {
      // 非 JSON 回應就沿用白話預設錯誤。
    }
    throw new Error(message);
  }
}

const base = (brandId: string) => `/api/intake/brands/${encodeURIComponent(brandId)}`;

export const fetchPersonas = (brandId: string): Promise<PersonaBundle> => getJson(`${base(brandId)}/personas`);

export const updatePersona = (
  brandId: string,
  personaId: string,
  fields: Pick<Persona, "title" | "when_needed" | "care_about" | "hesitation" | "where_to_find">,
): Promise<void> => putJson(`${base(brandId)}/personas/${encodeURIComponent(personaId)}`, fields);

/** 後端 202 回傳 {generation}，在 API 邊界直接拆開，元件不碰傳輸包裝。 */
export const regeneratePersonas = (brandId: string): Promise<PersonaGeneration> =>
  postJson<{ generation: PersonaGeneration }>(`${base(brandId)}/personas/regenerate`).then((body) => body.generation);
