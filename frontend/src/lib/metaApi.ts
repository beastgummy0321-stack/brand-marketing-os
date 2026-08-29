/** frontend/src/lib/metaApi.ts — Meta 廣告帳戶連接（票 04）。對應 app/meta/routes.py。
 * 這批路由用 ApiError 信封（{"error": {"code","message","details"}}，票 03-1 附錄 A），
 * 不是 /api/settings 那種 {data, generated_at} 信封——照抄
 * frontend/src/components/auth/AcceptInvitePage.tsx 已經在用的解析方式，不要自己
 * 另外發明一套錯誤格式。 */
import { apiFetch } from "./http";

export interface MetaAccount {
  id: string;
  account_id: string;
  name: string;
  currency: string;
  connected_at: string;
  bound_brand_ids: string[];
}

export interface MetaAccountsData {
  token_tail: string | null;
  accounts: MetaAccount[];
}

interface ErrorEnvelope {
  error: { code: string; message: string };
}

async function readOrThrow<T>(res: Response, fallback: string): Promise<T> {
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as ErrorEnvelope | null;
    throw new Error(body?.error?.message ?? fallback);
  }
  return res.json() as Promise<T>;
}

export async function connectMetaToken(token: string): Promise<MetaAccountsData> {
  const res = await apiFetch("/api/meta/token", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
  return readOrThrow<MetaAccountsData>(res, `連接失敗（狀態碼 ${res.status}）`);
}

export async function fetchMetaAccounts(): Promise<MetaAccountsData> {
  const res = await apiFetch("/api/meta/accounts");
  return readOrThrow<MetaAccountsData>(res, `讀取失敗（狀態碼 ${res.status}）`);
}

export async function bindMetaAccount(brandId: string, adAccountId: string): Promise<void> {
  const res = await apiFetch(
    `/api/meta/brands/${encodeURIComponent(brandId)}/accounts/${encodeURIComponent(adAccountId)}`,
    { method: "POST" },
  );
  await readOrThrow(res, `綁定失敗（狀態碼 ${res.status}）`);
}

export async function unbindMetaAccount(brandId: string, adAccountId: string): Promise<void> {
  const res = await apiFetch(
    `/api/meta/brands/${encodeURIComponent(brandId)}/accounts/${encodeURIComponent(adAccountId)}`,
    { method: "DELETE" },
  );
  await readOrThrow(res, `取消綁定失敗（狀態碼 ${res.status}）`);
}
