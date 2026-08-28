import { apiFetch } from "./http";

export interface CockpitLegacyCard {
  key: "wisdom" | "effective_direction" | "prohibition" | "material_stock" | "customer_understanding";
  value: number | boolean;
}

export interface TaskCard {
  id: string;
  title: string;
  done: boolean;
}

export interface CockpitExtras {
  legacy: CockpitLegacyCard[];
  task_cards: TaskCard[];
  todo3: { product_completeness: number; good_customer_defined: boolean; reply_speed: null };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(path, init);
  if (!response.ok) throw new Error(`讀取失敗（狀態碼 ${response.status}）`);
  return response.json() as Promise<T>;
}

const base = (brandId: string) => `/api/campaigns/brands/${encodeURIComponent(brandId)}`;

export function fetchCockpitExtras(brandId: string): Promise<CockpitExtras> {
  return request(base(brandId) + "/cockpit-extras");
}

export function completeTaskCard(brandId: string, cardId: string): Promise<TaskCard> {
  return request(base(brandId) + `/task-cards/${encodeURIComponent(cardId)}/done`, { method: "POST" });
}
