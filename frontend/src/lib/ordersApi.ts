/** 訂單總覽唯讀 API（票 01-orders-page-read）。 */

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

export interface OrdersPageData {
  brand: { id: string; name: string };
  summary: OrderSummary;
  orders: {
    items: OrderListItem[];
    page: number;
    page_size: number;
    total: number;
  };
}

export async function fetchOrders(brandId: string, page = 1): Promise<OrdersPageData> {
  const res = await fetch(`/api/brands/${encodeURIComponent(brandId)}/orders?page=${page}`);
  if (!res.ok) {
    throw new Error(res.status === 404 ? "找不到這個品牌。" : `讀取失敗（狀態碼 ${res.status}）`);
  }
  return (await res.json()) as OrdersPageData;
}
