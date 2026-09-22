import { useEffect, useState, type ReactNode } from "react";
import {
  Link,
  Navigate,
  Outlet,
  Route,
  Routes,
  useLocation,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { AdsHomePage, AllCampaignsPage, CampaignDetailPage, CampaignTargetPage, CampaignWorkspace, ConfirmBriefPage, ConfirmPage, DataConnectionsPage, HandoffPage, NewCampaignPage, PreparePage, ReviewEvidencePage, VerifyPage } from "@/components/ads";
import { AppShell } from "@/components/layout/AppShell";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { ErrorBoundary } from "@/components/layout/ErrorBoundary";
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
import { SettingsPage } from "@/components/settings/SettingsPage";
import { FreeJobPage, PackPage, SetStudioPage, WorkbenchHomePage } from "@/components/workbench";
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
        <Route path="/brands/:brandId/workbench/new" element={<WorkbenchNewRoute />} />
        <Route
          path="/brands/:brandId/workbench/packs/:packId"
          element={<WorkbenchPackRoute />}
        />
        <Route
          path="/brands/:brandId/workbench/packs/:packId/sets/:setId"
          element={<WorkbenchSetRoute />}
        />
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
        <Route path="/brands/:brandId/ads" element={<AdsHomeRoute />} />
        <Route path="/brands/:brandId/ads/new" element={<AdsNewRoute />} />
        <Route path="/brands/:brandId/ads/new/:campaignId" element={<AdsConfirmBriefRoute />} />
        <Route path="/brands/:brandId/ads/campaigns" element={<AllCampaignsRoute />} />
        <Route
          path="/brands/:brandId/ads/campaigns/:campaignId"
          element={<AdsCampaignRoute />}
        />
        <Route
          path="/brands/:brandId/ads/campaigns/:campaignId/target"
          element={<AdsTargetRoute />}
        />
        <Route
          path="/brands/:brandId/ads/campaigns/:campaignId/detail"
          element={<AdsCampaignDetailRoute />}
        />
        <Route path="/brands/:brandId/ads/connections" element={<AdsConnectionsRoute />} />
        <Route
          path="/brands/:brandId/ads/campaigns/:campaignId/propose/pause/:entityId"
          element={<AdsProposePauseRoute />}
        />
        <Route
          path="/brands/:brandId/ads/campaigns/:campaignId/review/:entityId"
          element={<AdsReviewEntryRoute />}
        />
        <Route
          path="/brands/:brandId/ads/campaigns/:campaignId/reviews/:reviewId"
          element={<AdsReviewRoundRoute />}
        />
        <Route
          path="/brands/:brandId/ads/campaigns/:campaignId/reviews/:reviewId/prepare"
          element={<AdsPrepareRoute />}
        />
        <Route
          path="/brands/:brandId/ads/campaigns/:campaignId/changes/:setId/confirm"
          element={<AdsChangeConfirmRoute />}
        />
        <Route
          path="/brands/:brandId/ads/campaigns/:campaignId/changes/:setId/handoff"
          element={<AdsChangeHandoffRoute />}
        />
        <Route
          path="/brands/:brandId/ads/campaigns/:campaignId/changes/:setId/verify"
          element={<AdsChangeVerifyRoute />}
        />
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
  const location = useLocation();
  return (
    <QueryClientProvider client={client}>
      <WorkspaceProvider>
        <AppShell>
          <ErrorBoundary key={location.pathname}>
            <Outlet />
          </ErrorBoundary>
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

/** 素材工作檯入口（F02-I07，`ARCHITECTURE.md` §5.1-§5.3）：任務包 → 素材組 → 產物 → 版本
 * 四層 IA 的第一頁。`…/workbench/new`／`…/workbench/packs/:packId`／
 * `…/workbench/packs/:packId/sets/:setId` 三條路由由 F02-I10／I08／I09 各自加上，
 * 這支只加自己這一條（F02-I07 → I08 → I09 → I10 是一條鏈，同一批檔案不並行）。 */
function WorkbenchRoute() {
  const { brandId } = useParams<{ brandId: string }>();
  return (
    <>
      <WorkbenchHomePage brandId={brandId ?? ""} />
    </>
  );
}

/** 自由創作（F02-I10）：鏈的最後一支，`…/workbench/new`。`?type=` 由入口「快速開始」帶進來
 * 預選素材類型，頁面自己讀 `useSearchParams`，這裡只傳 `brandId`。 */
function WorkbenchNewRoute() {
  const { brandId } = useParams<{ brandId: string }>();
  return (
    <>
      <FreeJobPage brandId={brandId ?? ""} />
    </>
  );
}

/** 任務包頁（F02-I08）：`…/workbench/packs/:packId` 一條路由，鏈上的下一支
 * （F02-I09，`…/workbench/packs/:packId/sets/:setId`）之後才加。 */
function WorkbenchPackRoute() {
  const { brandId, packId } = useParams<{ brandId: string; packId: string }>();
  return (
    <>
      <PackPage brandId={brandId ?? ""} packId={packId ?? ""} />
    </>
  );
}

/** 素材組 studio（F02-I09）：`…/workbench/packs/:packId/sets/:setId` 最後一條，鏈到此結束
 * （F02-I10 是 `…/workbench/new`，不再碰這三支檔案的這段）。 */
function WorkbenchSetRoute() {
  const { brandId, packId, setId } = useParams<{
    brandId: string;
    packId: string;
    setId: string;
  }>();
  return (
    <>
      <SetStudioPage brandId={brandId ?? ""} packId={packId ?? ""} setId={setId ?? ""} />
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

/** 投放中心首頁（F03-I13）：Campaign 清單＋建立入口，取代檔期規劃。 */
function AdsHomeRoute() {
  const { brandId } = useParams<{ brandId: string }>();
  return (
    <>
      <AdsHomePage brandId={brandId ?? ""} />
    </>
  );
}

/** 建立 Campaign（F03-I13）：一句話描述目標 → 行銷駕駛艙規劃初版策略。 */
function AdsNewRoute() {
  const { brandId } = useParams<{ brandId: string }>();
  return (
    <>
      <NewCampaignPage brandId={brandId ?? ""} />
    </>
  );
}

/** 建立 Campaign 步驟二（F04-I12）：理解如下，確認欄位才花第二次模型錢。 */
function AdsConfirmBriefRoute() {
  const { brandId, campaignId } = useParams<{ brandId: string; campaignId: string }>();
  return (
    <>
      <ConfirmBriefPage brandId={brandId ?? ""} campaignId={campaignId ?? ""} />
    </>
  );
}

/** 所有 Campaign 清單（F04-I10）。 */
function AllCampaignsRoute() {
  const { brandId } = useParams<{ brandId: string }>();
  return <AllCampaignsPage brandId={brandId ?? ""} />;
}

/** Campaign 五分頁工作區（F03-I13 起占位，F03-I14 起是真的內容）。 */
function AdsCampaignRoute() {
  const { brandId, campaignId } = useParams<{ brandId: string; campaignId: string }>();
  return (
    <>
      <CampaignWorkspace brandId={brandId ?? ""} campaignId={campaignId ?? ""} />
    </>
  );
}

/** 活動目標設定頁（F19-I05，v7 原型「設定目標」畫面）：判斷這個活動好壞的成果與成本門檻，
 * `AdsCampaignRoute` 卡片的「設定目標／調整目標」連結會導來這裡。`key={campaignId}` 讓
 * react-router 換活動時整支重新掛載——同一條 route element，不換這個就會沿用同一個元件
 * instance，上一個活動的草稿／baseline 會被誤帶到下一個活動（F19 repair #6）。 */
function AdsTargetRoute() {
  const { brandId, campaignId } = useParams<{ brandId: string; campaignId: string }>();
  return (
    <>
      <CampaignTargetPage key={campaignId} brandId={brandId ?? ""} campaignId={campaignId ?? ""} />
    </>
  );
}

/** 活動詳情頁（F20-I02，v7 原型 `campPage()`）：家頁的活動卡名稱與佇列的「看證據」都落在
 * 這裡；原本的五分頁工作區網址（`AdsCampaignRoute`）不變、由這頁的「全部資料 ›」進入。
 * `key={campaignId}` 理由同 `AdsTargetRoute`——換活動要整支重新掛載，不沿用上一個活動的
 * 展開／高亮狀態。 */
function AdsCampaignDetailRoute() {
  const { brandId, campaignId } = useParams<{ brandId: string; campaignId: string }>();
  return <CampaignDetailPage key={campaignId} brandId={brandId ?? ""} campaignId={campaignId ?? ""} />;
}

/** 資料連線頁（F21-I02，v7 原型 `connections()`）：投放中心倚賴的五個資料來源各自的狀態，
 * 家頁與月預算卡的「查看資料連線」都落在這裡。 */
function AdsConnectionsRoute() {
  const { brandId } = useParams<{ brandId: string }>();
  return <DataConnectionsPage brandId={brandId ?? ""} />;
}

/** 停損提議確認頁（propose route，F22-I02，v7 原型 `confirmPage()`）：三步驟輕流程第一步，
 * `queue` 裡的停損列進來時還沒有 change set，草稿在第一次核准／拒絕／暫緩才即時組出來
 * （`ConfirmPage` 自己的邏輯，這裡只負責帶參數）。`key` 用 entityId，換一則廣告要整支重新
 * 掛載（理由同 `AdsTargetRoute`）。 */
function AdsProposePauseRoute() {
  const { brandId, campaignId, entityId } = useParams<{ brandId: string; campaignId: string; entityId: string }>();
  return (
    <ConfirmPage key={`propose-${entityId}`} brandId={brandId ?? ""} campaignId={campaignId ?? ""} entityId={entityId ?? ""} />
  );
}

/** 六步流程「看證據」的入口（review route，F23-I02，v7 原型 `review()`）：`worse` 列還沒有檢討
 * 回合時進來，找到或建立回合後就轉導去正典的 `reviews/:reviewId` 網址——這裡只負責帶參數，
 * 轉導與建立回合的邏輯在 `ReviewEvidencePage` 自己（同 `AdsProposePauseRoute` 的分工）。 */
function AdsReviewEntryRoute() {
  const { brandId, campaignId, entityId } = useParams<{ brandId: string; campaignId: string; entityId: string }>();
  return (
    <ReviewEvidencePage key={`review-entry-${entityId}`} brandId={brandId ?? ""} campaignId={campaignId ?? ""} entityId={entityId ?? ""} />
  );
}

/** 六步流程「看證據」的正典網址（reviews/:reviewId route，F23-I02）：檢討回合已存在時直接讀。 */
function AdsReviewRoundRoute() {
  const { brandId, campaignId, reviewId } = useParams<{ brandId: string; campaignId: string; reviewId: string }>();
  return (
    <ReviewEvidencePage key={`review-round-${reviewId}`} brandId={brandId ?? ""} campaignId={campaignId ?? ""} reviewId={reviewId ?? ""} />
  );
}

/** 六步流程「選方向」頁（reviews/:reviewId/prepare route，F23-I03，v7 原型 `prepare()`）：檢討
 * 回合已存在時的正典網址；非法步驟（還沒判讀完、已經暫緩／無法判定）由 `PreparePage` 自己轉去
 * 看證據頁（同 `AdsReviewRoundRoute` 的分工）。 */
function AdsPrepareRoute() {
  const { brandId, campaignId, reviewId } = useParams<{ brandId: string; campaignId: string; reviewId: string }>();
  return (
    <PreparePage key={`review-prepare-${reviewId}`} brandId={brandId ?? ""} campaignId={campaignId ?? ""} reviewId={reviewId ?? ""} />
  );
}

/** 三步驟輕流程的「確認提議」頁（changes/:setId route，F22-I02）：change set 已存在時的正典
 * 網址；非 confirm 步驟的清單由 `ConfirmPage` 自己導去正確步驟（`flow/changeFlow.ts`）。 */
function AdsChangeConfirmRoute() {
  const { brandId, campaignId, setId } = useParams<{ brandId: string; campaignId: string; setId: string }>();
  return <ConfirmPage key={`set-${setId}`} brandId={brandId ?? ""} campaignId={campaignId ?? ""} setId={setId ?? ""} />;
}

/** 三步驟輕流程的「到平台完成」頁（changes/:setId/handoff route，F22-I03）：change set 一定
 * 已核准，草稿與 propose 網址都是上一步（`AdsChangeConfirmRoute`）的事，這裡只負責帶參數。 */
function AdsChangeHandoffRoute() {
  const { brandId, campaignId, setId } = useParams<{ brandId: string; campaignId: string; setId: string }>();
  return <HandoffPage key={`set-${setId}`} brandId={brandId ?? ""} campaignId={campaignId ?? ""} setId={setId ?? ""} />;
}

/** 三步驟輕流程的「核對結果」頁（changes/:setId/verify route，F22-I04）：change set 一定已核准
 * 且至少回報過一次，草稿、核准與到平台完成都是前兩步（`AdsChangeConfirmRoute`／
 * `AdsChangeHandoffRoute`）的事，這裡只負責帶參數。 */
function AdsChangeVerifyRoute() {
  const { brandId, campaignId, setId } = useParams<{ brandId: string; campaignId: string; setId: string }>();
  return <VerifyPage key={`set-${setId}`} brandId={brandId ?? ""} campaignId={campaignId ?? ""} setId={setId ?? ""} />;
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
