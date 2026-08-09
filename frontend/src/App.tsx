import { useEffect, useState, type ReactNode } from "react";
import { Navigate, Route, Routes, useParams, useSearchParams } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { CockpitPage } from "@/components/cockpit/CockpitPage";
import { BrandCard } from "@/components/overview/BrandCard";
import { MatrixPage } from "@/components/workbench/MatrixPage";
import { WorkbenchPage } from "@/components/workbench/WorkbenchPage";
import { fetchOverview, type DashboardBrandCard } from "@/lib/api";

/** 新殼唯一進入點。路徑式路由（票 05-spa-routing，裝 react-router-dom，basename="/app"
 * 見 main.tsx）：`/` 是跨品牌總覽（票 02），`/brands/:brandId` 是單品牌駕駛艙（票 03）。
 * production 的 `/app` StaticFiles 掛載已加子路徑 catch-all（app/main.py），子路徑
 * 直接整理／分享網址不會 404，React Router 接手決定畫面。
 *
 * 21 支廣告頁重建會在 `/brands/:brandId` 之下疊檔期、步驟這些更深層級——現在只有
 * 一顆元件掛在這個路徑，之後要加子路徑（如 `/brands/:brandId/cycles/:cycleId`）
 * 直接在 `<Routes>` 裡加同層或巢狀 `<Route>` 即可，不必重構這裡的結構。
 *
 * 舊書籤 `?brand=<id>` 仍要能用：根路徑先看查詢字串，有就轉去新網址（見 RootRoute）。 */
function App() {
  return (
    <Routes>
      <Route path="/" element={<RootRoute />} />
      <Route path="/brands/:brandId" element={<BrandRoute />} />
      <Route path="/brands/:brandId/workbench" element={<WorkbenchRoute />} />
      <Route path="/brands/:brandId/workbench/:cycleId" element={<MatrixRoute />} />
    </Routes>
  );
}

/** 根路徑：舊查詢字串網址 `/app/?brand=<id>` 轉到新的 `/app/brands/<id>`，書籤不斷。 */
function RootRoute() {
  const [params] = useSearchParams();
  const legacyBrandId = params.get("brand");
  if (legacyBrandId) {
    return <Navigate to={`/brands/${encodeURIComponent(legacyBrandId)}`} replace />;
  }
  return (
    <AppShell brandId={null}>
      <Overview />
    </AppShell>
  );
}

function BrandRoute() {
  const { brandId } = useParams<{ brandId: string }>();
  return (
    <AppShell brandId={brandId ?? null}>
      <CockpitPage brandId={brandId ?? ""} />
    </AppShell>
  );
}

/** 素材工作檯入口（畫面1，票 15-workbench-entry）。 */
function WorkbenchRoute() {
  const { brandId } = useParams<{ brandId: string }>();
  return (
    <AppShell brandId={brandId ?? null}>
      <WorkbenchPage brandId={brandId ?? ""} />
    </AppShell>
  );
}

/** 矩陣頁（畫面2）路由殼：本票只接路由，內容留給票 16-matrix-page。 */
function MatrixRoute() {
  const { brandId, cycleId } = useParams<{ brandId: string; cycleId: string }>();
  return (
    <AppShell brandId={brandId ?? null}>
      <MatrixPage brandId={brandId ?? ""} cycleId={cycleId ?? ""} />
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
