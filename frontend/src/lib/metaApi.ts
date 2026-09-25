/** frontend/src/lib/metaApi.ts — Meta 廣告帳戶連接（票 04）。對應 app/meta/routes.py。
 * 這批路由用 ApiError 信封（{"error": {"code","message","details"}}，票 03-1 附錄 A），
 * 不是 /api/settings 那種 {data, generated_at} 信封——照抄
 * frontend/src/components/auth/AcceptInvitePage.tsx 已經在用的解析方式，不要自己
 * 另外發明一套錯誤格式。 */
import { apiFetch, errorMessageFrom } from "./http";

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
    throw new Error(errorMessageFrom(body, fallback));
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

/** 票 05：品牌頁的本月 Meta 花費／成效。roas 為 null＝未追蹤（不是 0），對應
 * app/meta/routes.py CampaignSpendOut——這一頁刻意不叫「0」，兩者是不同的事實。 */
export interface MetaCampaignSpend {
  campaign_id: string;
  campaign_name: string;
  spend: number;
  impressions: number;
  clicks: number;
  roas: number | null;
}

export interface MetaSpendSummary {
  last_pull_at: string | null;
  /** F31-I03: newest read time of the rows summed here; null only when there are no rows. */
  data_pulled_at: string | null;
  /** F31-I03: the rows' attribution window in words (e.g. 點擊後 7 天＋瀏覽後 1 天). */
  attribution_label: string | null;
  campaigns: MetaCampaignSpend[];
  total: MetaCampaignSpend;
}

export async function fetchMetaSpend(brandId: string): Promise<MetaSpendSummary> {
  const res = await apiFetch(`/api/meta/brands/${encodeURIComponent(brandId)}/spend`);
  return readOrThrow<MetaSpendSummary>(res, `讀取失敗（狀態碼 ${res.status}）`);
}

/** 票 past-ads/02：37 個月補拉（ADR 0067 §1.8），一個組織一個背景工作。這裡只出 client——
 * 沒有元件用它，接的元件在票 04。 */
export interface MetaBackfillStartResult {
  started: boolean;
  running: boolean;
}

export interface MetaBackfillStatus {
  running: boolean;
  earliest_spend_date: string | null;
  latest_spend_date: string | null;
  ad_rows: number;
}

export async function startMetaBackfill(brandId: string): Promise<MetaBackfillStartResult> {
  const res = await apiFetch(`/api/meta/brands/${encodeURIComponent(brandId)}/backfill`, {
    method: "POST",
  });
  return readOrThrow<MetaBackfillStartResult>(res, `啟動失敗（狀態碼 ${res.status}）`);
}

export async function fetchMetaBackfillStatus(brandId: string): Promise<MetaBackfillStatus> {
  const res = await apiFetch(`/api/meta/brands/${encodeURIComponent(brandId)}/backfill`);
  return readOrThrow<MetaBackfillStatus>(res, `讀取失敗（狀態碼 ${res.status}）`);
}
