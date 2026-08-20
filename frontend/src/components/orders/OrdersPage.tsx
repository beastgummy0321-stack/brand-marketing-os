import { useEffect, useState, type ReactNode } from "react";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { Pager } from "@/components/layout/Pager";
import { Skeleton } from "@/components/layout/Skeleton";
import { StatBig } from "@/components/layout/StatBig";
import { formatCurrency } from "@/lib/format";
import { fetchOrders, type OrdersPageData, type SkuMargin } from "@/lib/ordersApi";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: OrdersPageData };

function displayNumber(value: number | null): string {
  return value === null ? "累積中" : value.toLocaleString("zh-TW");
}

function displayPercent(value: number | null): string {
  return value === null ? "累積中" : `${Math.round(value * 100)}%`;
}

function displayMargin(value: SkuMargin["margin"]): string {
  return value === null ? "未登記成本" : formatCurrency(value);
}

/** 訂單總覽：只讀取已匯入資料，不在此頁新增任何訂單寫入動作。 */
export function OrdersPage({ brandId }: { brandId: string }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  function load(page = 1) {
    setState({ status: "loading" });
    fetchOrders(brandId, page)
      .then((data) => setState({ status: "ready", data }))
      .catch((err: unknown) =>
        setState({
          status: "error",
          message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。",
        }),
      );
  }

  useEffect(() => {
    load();
  }, [brandId]);

  let content: ReactNode;
  if (state.status === "loading") {
    content = (
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          {Array.from({ length: 5 }, (_, index) => <Skeleton key={index} className="h-24" />)}
        </div>
        <Skeleton className="h-64 w-full" />
      </div>
    );
  } else if (state.status === "error") {
    content = <EmptyState title="讀取失敗" description={state.message} onAction={() => load()} actionLabel="重新載入" />;
  } else {
    const { brand, summary, orders } = state.data;
    const noData = !summary.has_history && orders.total === 0;
    const pageCount = Math.ceil(orders.total / orders.page_size);
    content = noData ? (
      <EmptyState
        title="還沒有訂單資料"
        description="把 EasyStore 訂單匯出檔拖進來，這頁就會出現營收、毛利與回購率。"
      />
    ) : (
      <>
        <div className="flex flex-col gap-1">
          <Breadcrumb items={[{ label: "跨品牌總覽", href: "/" }, { label: brand.name, href: `/brands/${brandId}` }, { label: "訂單與顧客" }]} />
          <h1 className="font-display text-2xl text-foreground">訂單與顧客</h1>
          <p className="text-sm text-muted-foreground">統計區間 {summary.since} ～ {summary.until}（最近 30 天）</p>
        </div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          <StatBig value={formatCurrency(summary.net_revenue)} label="實收營收" />
          <StatBig value={displayNumber(summary.order_count)} label="訂單數" />
          <StatBig value={formatCurrency(summary.average_order_value)} label="平均客單價" />
          <StatBig value={`${summary.new_customers}／${summary.existing_customers}`} label="新客／舊客" />
          <StatBig value={displayPercent(summary.repurchase_rate)} label="回購率" />
        </div>
        <section className="flex flex-col gap-3">
          <h2 className="font-display text-xl text-foreground">逐項商品毛利</h2>
          {summary.sku_margins.length === 0 ? (
            <p className="text-sm text-muted-foreground">這段期間還沒有可統計的 SKU 資料。</p>
          ) : (
            <Table>
              <thead className="bg-muted text-muted-foreground"><tr><Header>SKU</Header><Header>數量</Header><Header>營收</Header><Header>單位成本</Header><Header>毛利</Header></tr></thead>
              <tbody>{summary.sku_margins.map((item) => <tr key={item.sku} className="border-t border-border"><Cell>{item.sku}</Cell><Cell>{displayNumber(item.quantity)}</Cell><Cell>{formatCurrency(item.revenue)}</Cell><Cell>{item.unit_cost === null ? "未登記成本" : formatCurrency(item.unit_cost)}</Cell><Cell>{displayMargin(item.margin)}</Cell></tr>)}</tbody>
            </Table>
          )}
        </section>
        <section className="flex flex-col gap-3">
          <h2 className="font-display text-xl text-foreground">最近訂單</h2>
          <Table>
            <thead className="bg-muted text-muted-foreground"><tr><Header>訂單編號</Header><Header>日期</Header><Header>金額</Header><Header>訂單狀態</Header><Header>優惠碼</Header><Header>來源</Header></tr></thead>
            <tbody>{orders.items.map((item) => <tr key={item.id} className="border-t border-border"><Cell>{item.order_number}</Cell><Cell>{item.order_date ?? "—"}</Cell><Cell>{formatCurrency(item.total_amount)}</Cell><Cell>{item.order_status ?? "—"}</Cell><Cell>{item.voucher_code ?? "—"}</Cell><Cell>{item.attribution_override === "excluded" ? "非廣告來源" : "—"}</Cell></tr>)}</tbody>
          </Table>
          <Pager page={orders.page} pageCount={pageCount} totalCount={orders.total} onChange={load} />
        </section>
      </>
    );
  }

  return <div className="flex flex-col gap-5">{content}</div>;
}

function Table({ children }: { children: ReactNode }) {
  return <div className="overflow-x-auto rounded-md border border-border"><table className="w-full text-left text-sm">{children}</table></div>;
}

function Header({ children }: { children: ReactNode }) {
  return <th className="whitespace-nowrap px-3 py-2 font-medium">{children}</th>;
}

function Cell({ children }: { children: ReactNode }) {
  return <td className="whitespace-nowrap px-3 py-2 text-foreground">{children}</td>;
}
