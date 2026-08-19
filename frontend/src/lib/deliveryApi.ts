export interface DeliveryItem {
  id: string;
  copy: string;
  image_description: string;
  image_prompt: string;
}

export interface DeliveryView {
  status: "assembling" | "ready" | "failed";
  reason: string | null;
  items: DeliveryItem[];
  checks: { facts_confirmed: boolean[]; budget_confirmed: boolean; budget_cap: number };
}

export interface DeliveryActionCard {
  id: string;
  campaign_name: string;
  adset_name: string;
  ad_name: string;
  full_url: string;
  daily_budget: number;
  copy_text: string;
  image_prompts: string[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    let message = `處理失敗（狀態碼 ${response.status}）`;
    try {
      const body = (await response.json()) as { error?: string };
      if (body.error) message = body.error;
    } catch {
      // 回應不是 JSON，用預設訊息。
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

const base = (brandId: string, cycleId: string) => `/api/campaigns/${encodeURIComponent(brandId)}/${encodeURIComponent(cycleId)}/delivery`;

export function fetchDelivery(brandId: string, cycleId: string): Promise<DeliveryView> {
  return request(base(brandId, cycleId));
}

export function confirmDelivery(brandId: string, cycleId: string, facts: string[], budget: boolean): Promise<{ status: string; reason: string | null; action_cards: DeliveryActionCard[] }> {
  return request(base(brandId, cycleId) + "/confirm", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ facts, budget }),
  });
}

export function rejectDeliveryItem(brandId: string, cycleId: string, itemId: string): Promise<DeliveryView> {
  return request(base(brandId, cycleId) + `/items/${encodeURIComponent(itemId)}/reject`, { method: "POST" });
}
