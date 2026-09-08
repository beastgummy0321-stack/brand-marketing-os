import { useEffect, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useWorkspace } from "@/components/layout/WorkspaceContext";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/layout/ui/button";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { fetchLibrary, type LibraryData } from "@/lib/libraryApi";
import { BrandProfilePanel } from "./panels/BrandProfilePanel";
import { AssetsTab } from "./tabs/AssetsTab";
import { ChannelsTab } from "./tabs/ChannelsTab";
import { ClaimsTab } from "./tabs/ClaimsTab";
import { CoordinatesTab } from "./tabs/CoordinatesTab";
import { CustomerVoiceTab } from "./tabs/CustomerVoiceTab";
import { FactsTab } from "./tabs/FactsTab";
import { ResearchReportsTab } from "./tabs/ResearchReportsTab";
import { RulesTab } from "./tabs/RulesTab";

type TabKey =
  | "facts"
  | "rules"
  | "claims"
  | "assets"
  | "channels"
  | "customer-voice"
  | "research-reports"
  | "coordinates";

const TABS: { key: TabKey; label: string; count?: (data: LibraryData) => number }[] = [
  { key: "facts", label: "品牌事實", count: (d) => d.facts.length },
  { key: "rules", label: "限制規則", count: (d) => d.rules.length },
  { key: "claims", label: "宣稱", count: (d) => d.claims.length },
  { key: "assets", label: "官方素材", count: (d) => d.assets.length },
  { key: "channels", label: "自有渠道", count: (d) => d.channels.length },
  { key: "customer-voice", label: "顧客原話", count: (d) => d.customer_voices.length },
  { key: "research-reports", label: "調研報告" },
  { key: "coordinates", label: "創意座標" },
];

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: LibraryData };

/** 品牌智庫（S5，票 B2-library）：合併舊版 7 個 Jinja 頁面（`hub_home.html` 選單頁＋6 個
 * `hub_*.html` 子頁）成一個頁面、七個分頁籤、側板做所有寫入動作。一次整包讀（比照
 * `fetchCockpit()`），分頁切換不重新打 API——契約「要新增的 API」節明講的設計。 */
export function LibraryPage({ brandId }: { brandId: string }) {
  const { refreshBrands } = useWorkspace();
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [searchParams, setSearchParams] = useSearchParams();
  const [profileOpen, setProfileOpen] = useState(false);

  function load() {
    setState({ status: "loading" });
    fetchLibrary(brandId)
      .then((data) => setState({ status: "ready", data }))
      .catch((err: unknown) =>
        setState({
          status: "error",
          message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。",
        }),
      );
  }

  useEffect(load, [brandId]);

  const requestedTab = searchParams.get("tab");
  const activeTab: TabKey = TABS.some((t) => t.key === requestedTab) ? (requestedTab as TabKey) : "facts";

  function setTab(key: TabKey) {
    const next = new URLSearchParams(searchParams);
    next.set("tab", key);
    setSearchParams(next);
  }

  let content: ReactNode;
  if (state.status === "loading") {
    content = (
      <div className="flex flex-col gap-4">
        <div className="flex gap-2">
          {TABS.map((t) => (
            <Skeleton key={t.key} className="h-9 w-24" />
          ))}
        </div>
        <Skeleton className="h-10 w-full" />
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-20" />
        ))}
      </div>
    );
  } else if (state.status === "error") {
    content = (
      <EmptyState title="讀取失敗" description={state.message} onAction={load} actionLabel="重新載入" />
    );
  } else {
    const { data } = state;
    content = (
      <div className="workspace-split">
        <nav className="workspace-subnav" aria-label="智庫分類">
            {TABS.map((t) => (
              <button
                key={t.key}
                type="button"
                onClick={() => setTab(t.key)}
                aria-pressed={activeTab === t.key}
              >
                {t.label}
                {t.count && (
                  <span
                    className={
                      "rounded-full px-1.5 text-xs " +
                      (activeTab === t.key ? "bg-primary-foreground/20" : "bg-muted text-muted-foreground")
                    }
                  >
                    {t.count(data)}
                  </span>
                )}
              </button>
            ))}
        </nav>
        <div className="workspace-content surface p-5">

        {activeTab === "facts" && <FactsTab brandId={brandId} facts={data.facts} onChanged={load} />}
        {activeTab === "rules" && (
          <RulesTab brandId={brandId} rules={data.rules} products={data.products} onChanged={load} />
        )}
        {activeTab === "claims" && (
          <ClaimsTab brandId={brandId} claims={data.claims} products={data.products} onChanged={load} />
        )}
        {activeTab === "assets" && (
          <AssetsTab brandId={brandId} assets={data.assets} products={data.products} onChanged={load} />
        )}
        {activeTab === "channels" && (
          <ChannelsTab brandId={brandId} channels={data.channels} onChanged={load} />
        )}
        {activeTab === "customer-voice" && (
          <CustomerVoiceTab brandId={brandId} voices={data.customer_voices} onChanged={load} />
        )}
        {activeTab === "research-reports" && <ResearchReportsTab brandId={brandId} />}
        {activeTab === "coordinates" && <CoordinatesTab brandId={brandId} />}

        </div>
        {profileOpen && (
          <BrandProfilePanel
            brandId={brandId}
            profile={data.brand}
            onClose={() => setProfileOpen(false)}
            onSaved={() => {
              setProfileOpen(false);
              refreshBrands();
              load();
            }}
            onDeleted={() => {
              window.location.href = "/app/";
            }}
          />
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader title="品牌智庫" description={state.status === "ready" ? `${state.data.brand.name} · 品牌事實、素材與累積的經營知識` : "管理品牌知識與素材"} actions={
        <>
          {/* 品牌調研（建檔精靈）想按就按：沒跑過 → 直接是調研表單；跑過 → 「再跑一次調研」；
              跑到一半 → 接著上次的步驟。一次只開一輪（後端 restart 路由擋第二輪）。 */}
          <Button asChild variant="outline">
            <Link to={`/brands/${encodeURIComponent(brandId)}/intake`}>品牌調研</Link>
          </Button>
          <Button variant="outline" onClick={() => setProfileOpen(true)} disabled={state.status !== "ready"}>品牌資料</Button>
        </>
      }/>
      {content}
    </div>
  );
}
