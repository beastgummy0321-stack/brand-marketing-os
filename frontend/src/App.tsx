import { useEffect, useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { BrandCard } from "@/components/overview/BrandCard";
import { fetchOverview, type DashboardBrandCard } from "@/lib/api";

/** 跨品牌總覽首頁（票 02-overview-cards）：打儀表板 API，每個品牌一張卡。
 * 點卡進該品牌駕駛艙路徑（03 補內容），健康度燈號／KPI 圖表細節留給後續票。 */

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; cards: DashboardBrandCard[] };

function App() {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    fetchOverview()
      .then((cards) => {
        if (!cancelled) setState({ status: "ready", cards });
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
  }, []);

  return (
    <AppShell>
      {state.status === "loading" && (
        <EmptyState title="讀取中…" description="正在載入各品牌總覽。" />
      )}
      {state.status === "error" && (
        <EmptyState title="讀取失敗" description={state.message} />
      )}
      {state.status === "ready" && state.cards.length === 0 && (
        <EmptyState
          title="還沒有任何品牌"
          description="這裡會列出每個品牌的健康度卡片。先到舊版介面建立第一個品牌。"
          actionHref="/"
          actionLabel="前往舊版品牌總覽"
        />
      )}
      {state.status === "ready" && state.cards.length > 0 && (
        <div className="grid grid-cols-3 gap-4">
          {state.cards.map((card) => (
            <BrandCard key={card.brand_id} card={card} />
          ))}
        </div>
      )}
    </AppShell>
  );
}

function EmptyState({
  title,
  description,
  actionHref,
  actionLabel,
}: {
  title: string;
  description: string;
  actionHref?: string;
  actionLabel?: string;
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border bg-card p-12 text-center shadow-[var(--shadow-card)]">
      <h1 className="font-display text-2xl text-foreground">{title}</h1>
      <p className="max-w-md text-sm text-muted-foreground">{description}</p>
      {actionHref && actionLabel && (
        <a
          href={actionHref}
          className="mt-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
        >
          {actionLabel}
        </a>
      )}
    </div>
  );
}

export default App;
