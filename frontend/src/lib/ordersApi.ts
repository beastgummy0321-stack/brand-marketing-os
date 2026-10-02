/** 訂單總覽 API（票 01-orders-page-read／02-orders-page-actions）。 */

import { apiFetch, errorMessageFrom, throwIfFailed } from "./http";

export interface SkuMargin {
  sku: string;
  quantity: number;
  revenue: number;
  unit_cost: number | null;
  margin: number | null;
}

export interface OrderSummary {
  since: string;
  until: string;
  has_history: boolean;
  order_count: number;
  net_revenue: number | null;
  average_order_value: number | null;
  new_customers: number;
  existing_customers: number;
  repurchase_rate: number | null;
  repurchase_sample_size: number;
  sku_margins: SkuMargin[];
}

export interface OrderListItem {
  id: string;
  order_number: string;
  order_date: string | null;
  total_amount: number | null;
  order_status: string | null;
  voucher_code: string | null;
}

export interface PolicyChange {
  policy_type: string;
  policy_type_label: string;
  changed_at: string;
  description: string;
}

export interface ChannelEntry {
  channel: string;
  channel_label: string;
  entry_date: string;
  revenue: number | null;
  quantity: number | null;
  note: string;
}

/** 通路清單，手動對照 app/core/vocab.py CHANNEL_TYPES——各自維護，不共用一份。 */
export const CHANNEL_TYPES: [string, string][] = [
  ["website", "官方網站"],
  ["fb_page", "粉絲專頁"],
  ["ig_account", "Instagram 帳號"],
  ["line", "LINE 官方帳號"],
  ["marketplace", "平台商店"],
  ["physical_store", "實體店"],
];

/** 手動登錄用的通路清單＝上面那份扣掉官網：官網營收由訂單匯入自動記帳，手動再輸一筆
 * 會讓帳本跟訂單頁的實收對不起來（後端 `record_channel_entry` 也擋，這裡只是不給選）。 */
export const HAND_ENTRY_CHANNEL_TYPES: [string, string][] = CHANNEL_TYPES.filter(
  ([value]) => value !== "website",
);

export interface OrdersPageData {
  brand: { id: string; name: string };
  summary: OrderSummary;
  orders: {
    items: OrderListItem[];
    page: number;
    page_size: number;
    total: number;
  };
  policy_changes: PolicyChange[];
  channel_entries: ChannelEntry[];
}

export async function fetchOrders(brandId: string, page = 1): Promise<OrdersPageData> {
  const res = await apiFetch(`/api/brands/${encodeURIComponent(brandId)}/orders?page=${page}`);
  if (res.status === 404) throw new Error("找不到這個品牌。");
  await throwIfFailed(res, `讀取失敗（狀態碼 ${res.status}）`);
  return (await res.json()) as OrdersPageData;
}

async function postOrderAction(path: string, body: BodyInit, headers?: HeadersInit): Promise<string> {
  const res = await apiFetch(path, { method: "POST", body, headers });
  // 票 07-3：錯誤外殼交給 `http.ts` 那支共用解析（三種外殼都吃）。原本只認 `detail`，
  // 碰到 `web.ApiError` 的 `{"error": {"code","message"}}` 就退回 fallback，使用者看到
  // 「送出失敗（狀態碼 401）」而不是「請先登入」。成功時的 `message` 仍然自己讀。
  const payload = (await res.json()) as { message?: string };
  if (!res.ok) throw new Error(errorMessageFrom(payload, `送出失敗（狀態碼 ${res.status}）`));
  return payload.message ?? "已儲存。";
}

function actionPath(brandId: string, suffix: string): string {
  return `/api/brands/${encodeURIComponent(brandId)}/orders${suffix}`;
}

export function importOrdersFile(brandId: string, file: File): Promise<string> {
  const body = new FormData();
  body.append("drop_file", file);
  return postOrderAction(actionPath(brandId, "/import"), body);
}

export function saveSkuCost(brandId: string, sku: string, unitCost: string): Promise<string> {
  return postOrderAction(actionPath(brandId, "/sku-cost"), JSON.stringify({ sku, unit_cost: unitCost }), {
    "content-type": "application/json",
  });
}

export function createPolicyChange(
  brandId: string,
  fields: { policy_type: string; changed_at: string; description: string },
): Promise<string> {
  return postOrderAction(actionPath(brandId, "/policy-change"), JSON.stringify(fields), {
    "content-type": "application/json",
  });
}

export function createChannelEntry(
  brandId: string,
  fields: { channel: string; entry_date: string; revenue: string; quantity: string; note: string },
): Promise<string> {
  return postOrderAction(actionPath(brandId, "/channel-entry"), JSON.stringify(fields), {
    "content-type": "application/json",
  });
}

