import { useEffect, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { Pager } from "@/components/layout/Pager";
import { Skeleton } from "@/components/layout/Skeleton";
import { fetchProductList, optionLabel, type ProductListItem } from "@/lib/productsApi";
import { usePagination } from "@/lib/usePagination";
import { Badge } from "./shared/Badge";
import { ProductNewPanel } from "./panels/ProductNewPanel";

const ECONOMICS_LABEL: [string, string][] = [
  ["confirmed", "已填寫"],
  ["pending", "待確認"],
  ["none", "尚未填寫"],
];

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; items: ProductListItem[] };

/** 產品清單（S6，票 B2-products）：品牌智庫底下第二層資料——舊版 `hub_products.html` 表格
 * 改成這裡的清單，點名稱去詳情頁（下一步，符合五鐵則①）。 */
export function ProductListPage({ brandId }: { brandId: string }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [newPanelOpen, setNewPanelOpen] = useState(false);
  const navigate = useNavigate();
  const items = state.status === "ready" ? state.items : [];
  const { page, pageCount, totalCount, pageItems, goToPage, topRef } = usePagination(items);

  function load() {
    setState({ status: "loading" });
    fetchProductList(brandId)
      .then((items) => setState({ status: "ready", items }))
      .catch((err: unknown) =>
        setState({
          status: "error",
          message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。",
        }),
      );
  }

  useEffect(load, [brandId]);

  let content: ReactNode;
  if (state.status === "loading") {
    content = (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 3 }, (_, i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
    );
  } else if (state.status === "error") {
    content = <EmptyState title="讀取失敗" description={state.message} onAction={load} actionLabel="重新載入" />;
  } else if (state.items.length === 0) {
    content = (
      <EmptyState
        title="這個品牌底下還沒有產品"
        description="品牌可以沒有產品。但填了產品之後，之後的內容才講得到具體品項。"
        actionLabel="新增產品"
        onAction={() => setNewPanelOpen(true)}
      />
    );
  } else {
    content = (
      <div ref={topRef} className="flex flex-col gap-3">
        <div className="overflow-x-auto rounded-md border border-border">
          <table className="w-full text-left text-sm">
            <thead className="bg-muted text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">產品名稱</th>
                <th className="px-3 py-2 font-medium">事實數</th>
                <th className="px-3 py-2 font-medium">待確認</th>
                <th className="px-3 py-2 font-medium">產品經濟數字</th>
              </tr>
            </thead>
            <tbody>
              {pageItems.map((item) => (
                <tr key={item.id} className="border-t border-border">
                  <td className="px-3 py-2">
                    <button
                      type="button"
                      onClick={() => navigate(`/brands/${brandId}/products/${item.id}`)}
                      className="text-left font-medium text-primary hover:underline"
                    >
                      {item.name}
                    </button>
                    {item.status === "archived" && (
                      <span className="ml-2">
                        <Badge>已封存</Badge>
                      </span>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-foreground">{item.fact_count}</td>
                  <td className="whitespace-nowrap px-3 py-2">
                    {item.pending_fact_count > 0 && (
                      <button
                        type="button"
                        onClick={() => navigate(`/brands/${brandId}/products/${item.id}?tab=facts`)}
                        className="inline-flex items-center gap-1.5 text-warning hover:underline"
                      >
                        <span className="h-1.5 w-1.5 rounded-full bg-warning" aria-hidden="true" />
                        待確認 {item.pending_fact_count} 項
                      </button>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2">
                    <Badge tone={item.economics_status === "none" ? "neutral" : item.economics_status === "pending" ? "warning" : "success"}>
                      {optionLabel(ECONOMICS_LABEL, item.economics_status)}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Pager page={page} pageCount={pageCount} totalCount={totalCount} onChange={goToPage} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <Breadcrumb items={[{ label: "跨品牌總覽", href: "/" }, { label: "產品" }]} />
      <div className="flex items-center justify-between">
        <h1 className="font-display text-2xl text-foreground">產品</h1>
        <button
          type="button"
          onClick={() => setNewPanelOpen(true)}
          className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90"
        >
          新增產品
        </button>
      </div>
      {content}

      {newPanelOpen && (
        <ProductNewPanel
          brandId={brandId}
          onClose={() => setNewPanelOpen(false)}
          onCreated={(productId) => navigate(`/brands/${brandId}/products/${productId}`)}
        />
      )}
    </div>
  );
}
