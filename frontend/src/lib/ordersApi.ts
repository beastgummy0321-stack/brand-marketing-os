/** 訂單總覽 API（票 01-orders-page-read／02-orders-page-actions）。 */

import { apiFetch } from "./http";

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
  attribution_override: string | null;
}

export interface PolicyChange {
  policy_type: string;
  policy_type_label: string;
  changed_at: string;
  description: string;
}

export interface PharmacyBatch {
  batch_date: string;
  quantity: number | null;
  note: string;
}

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
  pharmacy_batches: PharmacyBatch[];
}

export async function fetchOrders(brandId: string, page = 1): Promise<OrdersPageData> {
  const res = await apiFetch(`/api/brands/${encodeURIComponent(brandId)}/orders?page=${page}`);
  if (!res.ok) {
    throw new Error(res.status === 404 ? "找不到這個品牌。" : `讀取失敗（狀態碼 ${res.status}）`);
  }
  return (await res.json()) as OrdersPageData;
}

async function postOrderAction(path: string, body: BodyInit, headers?: HeadersInit): Promise<string> {
  const res = await apiFetch(path, { method: "POST", body, headers });
  const payload = (await res.json()) as { message?: string; detail?: string };
  if (!res.ok) throw new Error(payload.detail ?? `送出失敗（狀態碼 ${res.status}）`);
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

export function createPharmacyBatch(
  brandId: string,
  fields: { batch_date: string; quantity: string; note: string },
): Promise<string> {
  return postOrderAction(actionPath(brandId, "/pharmacy-batch"), JSON.stringify(fields), {
    "content-type": "application/json",
  });
}

export function setOrderAttribution(brandId: string, orderId: string, excluded: boolean): Promise<string> {
  return postOrderAction(actionPath(brandId, `/${encodeURIComponent(orderId)}/attribution`), JSON.stringify({ excluded }), {
    "content-type": "application/json",
  });
}
