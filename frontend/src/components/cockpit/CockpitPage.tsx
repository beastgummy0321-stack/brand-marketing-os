import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { fetchOverview } from "@/lib/api";

/** 單品牌頁（`/brands/:brandId`）。
 *
 * 外殼切片（2026-08-28）：原本的駕駛艙（KPI 卡、營收 vs 花費主圖、成效釘選區、警示區、
 * AI 油錢錶、內容產線）整組隨 `app/ads/` 一起刪掉——那些數字全部來自廣告成效快照，
 * 沒有成效資料就沒有數字（HANDOFF-shell-slice.md §3.8）。這一頁刻意保留而不是刪掉：
 * 它是外殼儀表板未來的位置，現在先是品牌標題＋一句空態。
 *
 * 品牌名稱從跨品牌總覽那支既有端點取（`/api/dashboard/overview`），不另開新端點——
 * 這一頁還沒有自己的資料，多開一支只為了拿一個名字不划算。 */
type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; brandName: string | null };

export function CockpitPage({ brandId }: { brandId: string }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    fetchOverview()
      .then((cards) => {
        if (cancelled) return;
        const card = cards.find((c) => c.brand_id === brandId);
        setState({ status: "ready", brandName: card ? card.brand_name : null });
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setState({
            status: "error",
            message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [brandId]);

  const breadcrumb = (
    <Breadcrumb
      items={[
        { label: "跨品牌總覽", href: "/" },
        { label: state.status === "ready" && state.brandName ? state.brandName : "品牌" },
      ]}
    />
  );

  let content: ReactNode;
  if (state.status === "loading") {
    content = <EmptyState title="讀取中…" description="正在載入這個品牌。" />;
  } else if (state.status === "error") {
    content = (
      <EmptyState
        title="讀取失敗"
        description={state.message}
        actionHref="/"
        actionInternal
        actionLabel="回跨品牌總覽"
      />
    );
  } else if (state.brandName === null) {
    content = (
      <EmptyState
        title="找不到這個品牌"
        description="這個品牌可能已經被刪除，或者網址打錯了。"
        actionHref="/"
        actionInternal
        actionLabel="回跨品牌總覽"
      />
    );
  } else {
    content = (
      <div className="flex flex-col gap-6">
        <div className="flex items-center justify-between">
          <h1 className="font-display text-2xl text-foreground">{state.brandName}</h1>
          <Link
            to="/"
            className="text-sm font-medium text-primary underline-offset-4 hover:underline"
          >
            回跨品牌總覽
          </Link>
        </div>
        <EmptyState
          title="本期還沒有方案"
          description="產生本期方案的按鈕還沒接上來。品牌資料、產品與訂單可以先從左側選單進去看。"
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {breadcrumb}
      {content}
    </div>
  );
}
