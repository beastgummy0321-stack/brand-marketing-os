/** 待認領廣告 API（票 T5-01）：型別僅含後端 list_pending_claims 已提供且畫面會使用的欄位。 */

import { apiFetch } from "./http";

export interface PendingClaim {
  id: string;
  campaign_name: string | null;
  platform: string;
  first_seen_at: string;
  is_suggested: boolean;
}

interface Envelope<T> {
  data: T;
  generated_at: string;
}

export interface ClaimActionResult {
  ok: true;
  message: string;
}

function base(brandId: string) {
  return `/api/campaigns/brands/${encodeURIComponent(brandId)}/claims`;
}

async function responseError(res: Response, fallback: string): Promise<never> {
  try {
    const body = (await res.json()) as { detail?: string };
    if (body.detail) throw new Error(body.detail);
  } catch (error) {
    if (error instanceof Error) throw error;
  }
  throw new Error(fallback);
}

export async function fetchClaims(brandId: string): Promise<PendingClaim[]> {
  const res = await apiFetch(base(brandId));
  if (!res.ok) await responseError(res, `讀取失敗（狀態碼 ${res.status}）`);
  const body = (await res.json()) as Envelope<{ items: PendingClaim[] }>;
  return body.data.items;
}

async function act(brandId: string, discoveredId: string, action: "claim" | "ignore"): Promise<ClaimActionResult> {
  const res = await apiFetch(`${base(brandId)}/${encodeURIComponent(discoveredId)}/${action}`, { method: "POST" });
  if (!res.ok) await responseError(res, `處理失敗（狀態碼 ${res.status}）`);
  return (await res.json()) as ClaimActionResult;
}

export const claimCampaign = (brandId: string, discoveredId: string) => act(brandId, discoveredId, "claim");
export const ignoreCampaign = (brandId: string, discoveredId: string) => act(brandId, discoveredId, "ignore");
