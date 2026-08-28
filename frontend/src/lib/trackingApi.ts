/** T0 追蹤健檢＋安裝精靈 API 型別與呼叫（契約 `.scratch/grill/t0-tracking-wireframe.html`
 * 條文 1.1-1.9／2.1-2.7）。型別逐欄對照 `app/ads/routes_tracking_api.py`／
 * `app/ads/tracking.py`（查證日 2026-08-14），不是自創形狀。 */

import { apiFetch } from "./http";

export type TrackingChannelKey = "website" | "fb_page" | "ig_account" | "shopee" | "pharmacy";
export type TrackingStatus = "ok" | "warn" | "bad" | "off";
export type TrackingActionKind = "install" | "fill" | "none";

export interface TrackingAction {
  kind: TrackingActionKind;
  /** "ga4"／"pixel" 之一或兩者都有（app/ads/tracking.py _website_node）。 */
  missing: string[];
}

export interface TrackingChannel {
  key: TrackingChannelKey;
  status: TrackingStatus;
  message: string;
  sub: string | null;
  checked_at: string | null;
  hidden: boolean;
  action: TrackingAction;
}

export interface TrackingHealth {
  /** 固定五筆，含隱藏的（契約 1.2：隱藏的收進頁尾、可恢復）。 */
  channels: TrackingChannel[];
  /** 只算未隱藏的就緒數／總數（app/ads/tracking.py tracking_health）。 */
  ready: number;
  total: number;
}

export type RecheckStatus = "running" | "done" | "failed";

export interface RecheckState {
  status: RecheckStatus;
  message?: string;
}

interface Envelope<T> {
  data: T;
  generated_at: string;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await apiFetch(path);
  if (!res.ok) {
    throw new Error(res.status === 404 ? "找不到這個品牌。" : `讀取失敗（狀態碼 ${res.status}）`);
  }
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
      if (data.error) message = data.error;
    } catch {
      // 回應不是 JSON，用預設訊息。
    }
    throw new Error(message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const base = (brandId: string) => `/api/campaigns/brands/${encodeURIComponent(brandId)}/tracking-health`;

export const fetchTrackingHealth = (brandId: string): Promise<TrackingHealth> => getJson(base(brandId));

/** 重新檢查全部（契約 1.7）：背景執行，搭配 fetchTrackingRecheckStatus 輪詢。 */
export const startTrackingRecheck = (brandId: string): Promise<void> => postJson(`${base(brandId)}/recheck`);
export const fetchTrackingRecheckStatus = (brandId: string): Promise<RecheckState> =>
  getJson(`${base(brandId)}/recheck/status`);

/** 精靈頁「我裝好了，幫我檢查」（契約 2.4）：同步，回傳更新後的官網卡。
 * 這支 POST 跟 GET 一樣回信封 {data:…}，要拆過才是官網卡。 */
export const checkWebsiteNow = (brandId: string): Promise<TrackingChannel> =>
  postJson<Envelope<TrackingChannel>>(`${base(brandId)}/website/check`).then((body) => body.data);

export const setChannelHidden = (brandId: string, channelKey: TrackingChannelKey, hidden: boolean): Promise<void> =>
  postJson(`${base(brandId)}/${encodeURIComponent(channelKey)}/hidden`, { hidden });
