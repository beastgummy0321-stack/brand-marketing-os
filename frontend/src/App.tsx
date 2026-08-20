import { useEffect, useState, type ReactNode } from "react";
import { Link, Navigate, Route, Routes, useParams, useSearchParams } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { CampaignListPage } from "@/components/campaigns/CampaignListPage";
import { CockpitPage } from "@/components/cockpit/CockpitPage";
import { IntakeWizard } from "@/components/intake/IntakeWizard";
import { InboxPage } from "@/components/inbox/InboxPage";
import { LibraryPage } from "@/components/library/LibraryPage";
import { BrandCard } from "@/components/overview/BrandCard";
import { ProductDetailPage } from "@/components/products/ProductDetailPage";
import { ProductListPage } from "@/components/products/ProductListPage";
import { OrdersPage } from "@/components/orders/OrdersPage";
import { SettingsPage } from "@/components/settings/SettingsPage";
import { TrackingHealthPage } from "@/components/tracking/TrackingHealthPage";
import { TrackingSetupPage } from "@/components/tracking/TrackingSetupPage";
import { WarroomPage } from "@/components/warroom/WarroomPage";
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
      <Route path="/inbox" element={<InboxRoute />} />
      <Route path="/settings" element={<SettingsRoute />} />
      <Route path="/intake/new" element={<IntakeNewRoute />} />
      <Route path="/brands/:brandId" element={<BrandRoute />} />
      <Route path="/brands/:brandId/intake" element={<IntakeRoute />} />
      <Route path="/brands/:brandId/library" element={<LibraryRoute />} />
      <Route path="/brands/:brandId/products" element={<ProductListRoute />} />
      <Route path="/brands/:brandId/products/:productId" element={<ProductDetailRoute />} />
      <Route path="/brands/:brandId/orders" element={<OrdersRoute />} />
      <Route path="/brands/:brandId/campaigns" element={<CampaignListRoute />} />
      <Route path="/brands/:brandId/campaigns/new" element={<WarroomNewRoute />} />
      <Route path="/brands/:brandId/campaigns/:cycleId" element={<WarroomRoute />} />
      <Route path="/brands/:brandId/workbench" element={<WorkbenchRoute />} />
      <Route path="/brands/:brandId/workbench/:cycleId" element={<MatrixRoute />} />
      <Route path="/brands/:brandId/tracking" element={<TrackingHealthRoute />} />
      <Route path="/brands/:brandId/tracking/setup" element={<TrackingSetupRoute />} />
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

/** 收件匣（S2，票 B1-inbox）：跨品牌，不掛在 `/brands/:brandId` 之下。 */
function InboxRoute() {
  return (
    <AppShell brandId={null}>
      <InboxPage />
    </AppShell>
  );
}

/** 設定（S15，票 B1-settings）：跨品牌，不掛在 `/brands/:brandId` 之下。 */
function SettingsRoute() {
  return (
    <AppShell brandId={null}>
      <SettingsPage />
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

/** 建檔精靈：新品牌（S4，票 B3-intake）。跨品牌總覽「新增品牌」與各處「重新調研」共用
 * 同一個精靈容器，差別只在 `brandId` 有沒有值。 */
function IntakeNewRoute() {
  return (
    <AppShell brandId={null}>
      <div className="flex flex-col gap-4">
        <Breadcrumb items={[{ label: "跨品牌總覽", href: "/" }, { label: "新增品牌" }]} />
        <IntakeWizard brandId={null} />
      </div>
    </AppShell>
  );
}

function IntakeRoute() {
  const { brandId } = useParams<{ brandId: string }>();
  return (
    <AppShell brandId={brandId ?? null}>
      <div className="flex flex-col gap-4">
        <Breadcrumb items={[{ label: "跨品牌總覽", href: "/" }, { label: "建檔精靈" }]} />
        <IntakeWizard brandId={brandId ?? ""} />
      </div>
    </AppShell>
  );
}

/** 品牌智庫（S5，票 B2-library）：合併舊版 7 個 Jinja 頁面成一頁六分頁籤＋側板。 */
function LibraryRoute() {
  const { brandId } = useParams<{ brandId: string }>();
  return (
    <AppShell brandId={brandId ?? null}>
      <LibraryPage brandId={brandId ?? ""} />
    </AppShell>
  );
}

/** 產品清單（S6，票 B2-products）。 */
function ProductListRoute() {
  const { brandId } = useParams<{ brandId: string }>();
  return (
    <AppShell brandId={brandId ?? null}>
      <ProductListPage brandId={brandId ?? ""} />
    </AppShell>
  );
}

/** 產品詳情（S6，票 B2-products）。 */
function ProductDetailRoute() {
  const { brandId, productId } = useParams<{ brandId: string; productId: string }>();
  return (
    <AppShell brandId={brandId ?? null}>
      <ProductDetailPage brandId={brandId ?? ""} productId={productId ?? ""} />
    </AppShell>
  );
}

function OrdersRoute() {
  const { brandId } = useParams<{ brandId: string }>();
  return (
    <AppShell brandId={brandId ?? null}>
      <OrdersPage brandId={brandId ?? ""} />
    </AppShell>
  );
}

/** 檔期清單（S7，票 B4-campaigns）：搬家舊版 `ads_home`／`ads_history`／`ads_interview`
 * 三頁合一，見 `.scratch/grill/GRILL-B4-campaigns.md`。 */
function CampaignListRoute() {
  const { brandId } = useParams<{ brandId: string }>();
  return (
    <AppShell brandId={brandId ?? null}>
      <CampaignListPage brandId={brandId ?? ""} />
    </AppShell>
  );
}

/** S8 檔期作戰室：開新檔期（票 B4-warroom）。 */
function WarroomNewRoute() {
  const { brandId } = useParams<{ brandId: string }>();
  return (
    <AppShell brandId={brandId ?? null}>
      <WarroomPage brandId={brandId ?? ""} cycleId={null} />
    </AppShell>
  );
}

/** S8 檔期作戰室：既有檔期（票 B4-warroom）。 */
function WarroomRoute() {
  const { brandId, cycleId } = useParams<{ brandId: string; cycleId: string }>();
  return (
    <AppShell brandId={brandId ?? null}>
      <WarroomPage brandId={brandId ?? ""} cycleId={cycleId ?? ""} />
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

/** T0 追蹤健檢總覽（票 T0-tracking-health）。 */
function TrackingHealthRoute() {
  const { brandId } = useParams<{ brandId: string }>();
  return (
    <AppShell brandId={brandId ?? null}>
      <TrackingHealthPage brandId={brandId ?? ""} />
    </AppShell>
  );
}

/** T0 安裝精靈（官網追蹤，票 T0-tracking-health）。 */
function TrackingSetupRoute() {
  const { brandId } = useParams<{ brandId: string }>();
  return (
    <AppShell brandId={brandId ?? null}>
      <TrackingSetupPage brandId={brandId ?? ""} />
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
        description="這裡會列出每個品牌的健康度卡片。用建檔精靈建立第一個品牌。"
        actionHref="/intake/new"
        actionLabel="新增品牌"
        actionInternal
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
      <div className="flex items-center justify-between">
        <Breadcrumb items={[{ label: "跨品牌總覽" }]} />
        <Link
          to="/intake/new"
          className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90"
        >
          新增品牌
        </Link>
      </div>
      {content}
    </div>
  );
}

export default App;
