import { useEffect, useState, type ReactNode } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { CockpitPage } from "@/components/cockpit/CockpitPage";
import { BrandCard } from "@/components/overview/BrandCard";
import { fetchOverview, type DashboardBrandCard } from "@/lib/api";

/** 新殼唯一進入點。沒有路由庫（單頁面切兩顆元件，沒必要拉 react-router）：
 * `?brand=<id>` 存在就進單品牌駕駛艙（票 03），否則是跨品牌總覽（票 02）。
 * 用查詢字串而不是路徑片段，是因為 production 用 StaticFiles(html=True) 掛
 * frontend/dist，只有掛載根目錄會自動回退到 index.html，子路徑沒設 catch-all
 * 直接整理／分享網址會 404；查詢字串留在同一個根路徑，天生就不會撞到這個限制。 */
function App() {
  const brandId = new URLSearchParams(window.location.search).get("brand");
  return (
    <AppShell brandId={brandId}>
      {brandId ? <CockpitPage brandId={brandId} /> : <Overview />}
    </AppShell>
  );
}

/** 跨品牌總覽首頁（票 02-overview-cards）：打儀表板 API，每個品牌一張卡。
 * 點卡進該品牌駕駛艙（票 03）。 */
type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; cards: DashboardBrandCard[] };

function Overview() {
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

  let content: ReactNode;
  if (state.status === "loading") {
    content = <EmptyState title="讀取中…" description="正在載入各品牌總覽。" />;
  } else if (state.status === "error") {
    content = <EmptyState title="讀取失敗" description={state.message} />;
  } else if (state.cards.length === 0) {
    content = (
      <EmptyState
        title="還沒有任何品牌"
        description="這裡會列出每個品牌的健康度卡片。先到舊版介面建立第一個品牌。"
        actionHref="/"
        actionLabel="前往舊版品牌總覽"
      />
    );
  } else {
    content = (
      <div className="grid grid-cols-3 gap-4">
        {state.cards.map((card) => (
          <BrandCard key={card.brand_id} card={card} />
        ))}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <Breadcrumb items={[{ label: "跨品牌總覽" }]} />
      {content}
    </div>
  );
}

export default App;
