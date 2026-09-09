import { useEffect, useState, type ReactNode } from "react";
import {
  Link,
  Navigate,
  Outlet,
  Route,
  Routes,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { AcceptInvitePage } from "@/components/auth/AcceptInvitePage";
import { LoginPage } from "@/components/auth/LoginPage";
import { CockpitPage } from "@/components/cockpit/CockpitPage";
import { HistoryPage } from "@/components/intake/HistoryPage";
import { IntakeWizard } from "@/components/intake/IntakeWizard";
import { InboxPage } from "@/components/inbox/InboxPage";
import { LibraryPage } from "@/components/library/LibraryPage";
import { BrandCard } from "@/components/overview/BrandCard";
import { ProductDetailPage } from "@/components/products/ProductDetailPage";
import { ProductListPage } from "@/components/products/ProductListPage";
import { BrandReportPage } from "@/components/report/BrandReportPage";
import { OrdersPage } from "@/components/orders/OrdersPage";
import { SchedulePage } from "@/components/schedule/SchedulePage";
import { SettingsPage } from "@/components/settings/SettingsPage";
import { WorkbenchPage } from "@/components/workbench";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  WorkspaceProvider,
  useWorkspace,
} from "@/components/layout/WorkspaceContext";
import { PageHeader } from "@/components/layout/PageHeader";
import { useSession } from "@/lib/auth";
import { takePendingPath } from "@/lib/http";

/** 新殼唯一進入點。路徑式路由（票 05-spa-routing，裝 react-router-dom，basename="/app"
 * 見 main.tsx）：`/` 是跨品牌總覽（票 02），`/brands/:brandId` 是單品牌駕駛艙（票 03）。
 * production 的 `/app` StaticFiles 掛載已加子路徑 catch-all（app/main.py），子路徑
 * 直接整理／分享網址不會 404，React Router 接手決定畫面。
 *
 * 外殼切片（2026-08-28）：10 支相依於 `app/ads/` 的路由（檔期清單／作戰室／素材工作檯／
 * 矩陣／宣稱／累積智慧／追蹤健檢／安裝精靈／資料上手）連同頁面元件一起刪掉，**不做轉址**
 * ——轉址會讓一支死掉的頁面看起來還活著（HANDOFF-shell-slice.md §3.7）。它們之後由外殼的
 * 兩支新頁面（工單流＋儀表板）取代；要加子路徑直接在 `<Routes>` 裡加同層或巢狀
 * `<Route>` 即可，不必重構這裡的結構。
 *
 * 舊書籤 `?brand=<id>` 仍要能用：根路徑先看查詢字串，有就轉去新網址（見 RootRoute）。 */
function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginRoute />} />
      <Route path="/accept-invite" element={<AcceptInvitePage />} />
      <Route element={<RequireSession />}>
        <Route path="/" element={<RootRoute />} />
        <Route path="/inbox" element={<InboxRoute />} />
        <Route path="/settings" element={<SettingsRoute />} />
        <Route path="/intake/new" element={<IntakeNewRoute />} />
        <Route path="/brands/:brandId" element={<BrandRoute />} />
        <Route path="/brands/:brandId/intake" element={<IntakeRoute />} />
        <Route path="/brands/:brandId/intake/history" element={<HistoryRoute />} />
        <Route path="/brands/:brandId/library" element={<LibraryRoute />} />
        <Route path="/brands/:brandId/workbench" element={<WorkbenchRoute />} />
        <Route
          path="/brands/:brandId/products"
          element={<ProductListRoute />}
        />
        <Route
          path="/brands/:brandId/products/:productId"
          element={<ProductDetailRoute />}
        />
        <Route path="/brands/:brandId/orders" element={<OrdersRoute />} />
        <Route path="/brands/:brandId/report" element={<BrandReportRoute />} />
        <Route path="/brands/:brandId/schedule" element={<ScheduleRoute />} />
        <Route path="*" element={<NotFoundRoute />} />
      </Route>
    </Routes>
  );
}

/** 登入守門（票 03-2）：包住除了 `/login`／`/accept-invite` 以外的每一條路由（layout
 * route＋`<Outlet/>`，react-router v6 起的標準寫法，不用另外巢一層 `<Routes>`）。session
 * 從 `src/lib/auth.ts` 的 `useSession()` 讀，不直接戳 `localStorage`——session 有沒有
 * 過期、要不要刷新是 supabase-js 的事。 */
function RequireSession() {
  const { loading, session } = useSession();
  if (loading) {
    return <EmptyState title="讀取中…" description="正在確認登入狀態。" />;
  }
  if (!session) {
    return <Navigate to="/login" replace />;
  }
  return <AuthenticatedWorkspace key={session.user.id} />;
}

function AuthenticatedWorkspace() {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: 1, staleTime: 30000 } },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <WorkspaceProvider>
        <AppShell>
          <Outlet />
        </AppShell>
      </WorkspaceProvider>
    </QueryClientProvider>
  );
}

/** `/login`：已經登入的人不該停留在登入頁，轉去首頁（`useSession()` 收到
 * `onAuthStateChange` 廣播後這裡會自動重新渲染，登入成功不用自己 `navigate`）——除非
 * `lib/http.ts` 的 401 攔截器在導來這裡之前記了一個「原本要去哪裡」（票 03-3 §3，
 * 冷邀請連結那條路：沒登入點連結 → 401 → 被導來這裡 → 登入/註冊成功後要送回邀請頁，
 * 不是首頁）。用 `useEffect` 讀一次、清一次，不在 render 期間動 sessionStorage
 * （避免 React StrictMode 的 dev 期雙重呼叫把它提早清掉）。 */
function LoginRoute() {
  const { loading, session } = useSession();
  const [redirectTo, setRedirectTo] = useState<string | null>(null);

  useEffect(() => {
    if (session && redirectTo === null) {
      setRedirectTo(takePendingPath() ?? "/");
    }
  }, [session, redirectTo]);

  if (loading) return null;
  if (session) return redirectTo ? <Navigate to={redirectTo} replace /> : null;
  return <LoginPage />;
}

/** 根路徑：舊查詢字串網址 `/app/?brand=<id>` 轉到新的 `/app/brands/<id>`，書籤不斷。 */
function RootRoute() {
  const [params] = useSearchParams();
  const legacyBrandId = params.get("brand");
  if (legacyBrandId) {
    return (
      <Navigate to={`/brands/${encodeURIComponent(legacyBrandId)}`} replace />
    );
  }
  return (
    <>
      <Overview />
    </>
  );
}

/** 收件匣（S2，票 B1-inbox）：跨品牌，不掛在 `/brands/:brandId` 之下。 */
function InboxRoute() {
  return (
    <>
      <InboxPage />
    </>
  );
}

/** 設定（S15，票 B1-settings）：跨品牌，不掛在 `/brands/:brandId` 之下。 */
function SettingsRoute() {
  return (
    <>
      <SettingsPage />
    </>
  );
}

/** 未知網址（票 workbench-2/03，issue-unknown-url-renders-a-blank-page）：`<Routes>` 找不到
 * 更早的路由時落到這裡——放在 `RequireSession` 群組最後一個子路由，殼層與登入守門照樣套用
 * （不是獨立掛在 `RequireSession` 外面的一條路由，那樣未登入使用者打一個打錯的網址會看到
 * 沒有殼、沒有登入檢查的畫面）。 */
function NotFoundRoute() {
  return (
    <EmptyState
      title="找不到這一頁"
      description="網址可能過期或打錯了。"
      actionHref="/"
      actionLabel="回品牌總覽"
      actionInternal
    />
  );
}

function BrandRoute() {
  const { brandId } = useParams<{ brandId: string }>();
  return (
    <>
      <CockpitPage brandId={brandId ?? ""} />
    </>
  );
}

/** 建檔精靈：新品牌（S4，票 B3-intake）。跨品牌總覽「新增品牌」與各處「重新調研」共用
 * 同一個精靈容器，差別只在 `brandId` 有沒有值。 */
function IntakeNewRoute() {
  return (
    <>
      <div className="flex flex-col gap-4">
        <PageHeader
          title="新增品牌"
          description="建立品牌資料，讓後續的分析與規劃有據可循。"
        />
        <IntakeWizard brandId={null} />
      </div>
    </>
  );
}

function IntakeRoute() {
  const { brandId } = useParams<{ brandId: string }>();
  return (
    <>
      <div className="flex flex-col gap-4">
        <PageHeader
          title="品牌建檔"
          description="逐步補齊品牌資料與研究成果。"
        />
        <IntakeWizard brandId={brandId ?? ""} />
      </div>
    </>
  );
}

/** 把過去的廣告帶進來（S4，票 past-ads/04，ADR 0067）：跟 IntakeRoute 同一種殼——外面
 * 包麵包屑＋PageHeader，畫面本身在 HistoryPage。 */
function HistoryRoute() {
  const { brandId } = useParams<{ brandId: string }>();
  const { brands } = useWorkspace();
  const brand = brands.find((b) => b.brand_id === brandId);
  return (
    <div className="flex flex-col gap-4">
      <Breadcrumb
        items={[
          { label: "跨品牌總覽", href: "/" },
          { label: brand ? brand.brand_name : "品牌", href: `/brands/${brandId}` },
          { label: "把過去的廣告帶進來" },
        ]}
      />
      <PageHeader
        title="把過去的廣告帶進來"
        description="數字是 Meta 的，座標和理由是你的；這裡沒有 AI 在猜。"
      />
      <HistoryPage brandId={brandId ?? ""} />
    </div>
  );
}

/** 品牌智庫（S5，票 B2-library）：合併舊版 7 個 Jinja 頁面成一頁六分頁籤＋側板。 */
function LibraryRoute() {
  const { brandId } = useParams<{ brandId: string }>();
  return (
    <>
      <LibraryPage brandId={brandId ?? ""} />
    </>
  );
}

/** 素材工作檯（S16，票 workbench/04，ADR 0068）：文案、圖片提示詞與腳本在這裡生成。 */
function WorkbenchRoute() {
  const { brandId } = useParams<{ brandId: string }>();
  return (
    <>
      <WorkbenchPage brandId={brandId ?? ""} />
    </>
  );
}

/** 產品清單（S6，票 B2-products）。 */
function ProductListRoute() {
  const { brandId } = useParams<{ brandId: string }>();
  return (
    <>
      <ProductListPage brandId={brandId ?? ""} />
    </>
  );
}

/** 產品詳情（S6，票 B2-products）。 */
function ProductDetailRoute() {
  const { brandId, productId } = useParams<{
    brandId: string;
    productId: string;
  }>();
  return (
    <>
      <ProductDetailPage brandId={brandId ?? ""} productId={productId ?? ""} />
    </>
  );
}

function OrdersRoute() {
  const { brandId } = useParams<{ brandId: string }>();
  return (
    <>
      <OrdersPage brandId={brandId ?? ""} />
    </>
  );
}

/** 檔期規劃（票 07：最薄路徑）。 */
function ScheduleRoute() {
  const { brandId } = useParams<{ brandId: string }>();
  return (
    <>
      <SchedulePage brandId={brandId ?? ""} />
    </>
  );
}

/** 顧問分析報告（S13，票 03-brand-report-migration）。 */
function BrandReportRoute() {
  const { brandId } = useParams<{ brandId: string }>();
  return (
    <>
      <BrandReportPage brandId={brandId ?? ""} />
    </>
  );
}

/** 跨品牌總覽首頁（票 02-overview-cards）：打儀表板 API，每個品牌一張卡。
 * 點卡進該品牌駕駛艙（票 03）。 */
function Overview() {
  const { brands, brandsLoading, brandsError, refreshBrands } = useWorkspace();
  let content: ReactNode;
  if (brandsLoading) {
    content = <EmptyState title="讀取中…" description="正在載入各品牌總覽。" />;
  } else if (brandsError) {
    content = (
      <EmptyState
        title="讀取失敗"
        description={brandsError ?? "請稍後重試"}
        onAction={refreshBrands}
        actionLabel="重新載入"
      />
    );
  } else if (brands.length === 0) {
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
      <div className="grid grid-cols-2 xl:grid-cols-3 gap-5">
        {brands.map((card) => (
          <BrandCard key={card.brand_id} card={card} />
        ))}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <PageHeader
          title="品牌總覽"
          description="掌握每個品牌的近況，從這裡進入工作區。"
        />
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
