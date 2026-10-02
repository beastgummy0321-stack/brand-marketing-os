import { useEffect, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useWorkspace } from "@/components/layout/WorkspaceContext";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/layout/ui/button";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { LearningsTab, learningsCount, useCoordinateLearnings } from "@/components/ads";
import { fetchLibrary, type LibraryData } from "@/lib/libraryApi";
import { BrandProfilePanel } from "./panels/BrandProfilePanel";
import { AssetsTab } from "./tabs/AssetsTab";
import { ChannelsTab } from "./tabs/ChannelsTab";
import { ClaimsTab } from "./tabs/ClaimsTab";
import { CoordinatesTab } from "./tabs/CoordinatesTab";
import { CustomerVoiceTab } from "./tabs/CustomerVoiceTab";
import { FactsTab } from "./tabs/FactsTab";
import { RulesTab } from "./tabs/RulesTab";

type TabKey =
  | "facts"
  | "rules"
  | "claims"
  | "assets"
  | "channels"
  | "customer-voice"
  | "coordinates"
  | "ads-learnings";

const TABS: { key: TabKey; label: string; count?: (data: LibraryData) => number }[] = [
  { key: "facts", label: "品牌事實", count: (d) => d.facts.length },
  { key: "rules", label: "限制規則", count: (d) => d.rules.length },
  { key: "claims", label: "宣稱", count: (d) => d.claims.length },
  { key: "assets", label: "官方素材", count: (d) => d.assets.length },
  { key: "channels", label: "自有渠道", count: (d) => d.channels.length },
  { key: "customer-voice", label: "人物誌與顧客原話", count: (d) => d.customer_voices.length },
  { key: "coordinates", label: "創意座標" },
];

const ADVANCED_TAB_KEYS: TabKey[] = ["coordinates"];
/** F46-I06: the 「投放成果」 group of the sub-nav; its data is the ads module's Contract L read, not the library read. */
const LEARNINGS_TAB: TabKey = "ads-learnings";

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
  const learnings = useCoordinateLearnings(brandId);

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
  // The closeout's 「看學到什麼 →」 lands with `?campaign=<id>`; without a tab it means the learnings tab.
  const highlightCampaign = searchParams.get("campaign");
  const activeTab: TabKey =
    requestedTab === LEARNINGS_TAB || (requestedTab === null && highlightCampaign)
      ? LEARNINGS_TAB
      : TABS.some((t) => t.key === requestedTab) ? (requestedTab as TabKey) : "facts";
  const [advancedOpen, setAdvancedOpen] = useState(() => ADVANCED_TAB_KEYS.includes(activeTab));

  useEffect(() => {
    if (ADVANCED_TAB_KEYS.includes(activeTab)) setAdvancedOpen(true);
  }, [activeTab]);

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
      <div className="workspace-split max-[900px]:!grid-cols-1">
        <nav
          className="workspace-subnav max-[900px]:!static max-[900px]:!flex-row max-[900px]:overflow-x-auto max-[900px]:whitespace-nowrap max-[900px]:[&>p]:hidden max-[900px]:[&_button]:shrink-0"
          aria-label="智庫分類"
        >
            <p className="px-3 pb-2 pt-3 text-xs text-muted-foreground">品牌資料</p>
            {TABS.filter((tab) => !ADVANCED_TAB_KEYS.includes(tab.key)).map((t) => (
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
            <p className="mt-2 border-t border-border px-3 pb-2 pt-3 text-xs text-muted-foreground">投放成果</p>
            <button type="button" onClick={() => setTab(LEARNINGS_TAB)} aria-pressed={activeTab === LEARNINGS_TAB}>
              投放學到的
              {learnings.state.status === "ready" && (
                <span
                  className={
                    "rounded-full px-1.5 text-xs " +
                    (activeTab === LEARNINGS_TAB ? "bg-primary-foreground/20" : "bg-muted text-muted-foreground")
                  }
                >
                  {learningsCount(learnings.state.data)}
                </span>
              )}
            </button>
            <details
              className="mt-2 border-t border-border pt-2"
              open={advancedOpen}
              onToggle={(event) => setAdvancedOpen(event.currentTarget.open)}
            >
              <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-foreground">進階內容</summary>
              <div className="flex flex-col gap-1 pt-1">
                {TABS.filter((tab) => ADVANCED_TAB_KEYS.includes(tab.key)).map((t) => (
                  <button key={t.key} type="button" onClick={() => setTab(t.key)} aria-pressed={activeTab === t.key}>
                    {t.label}
                  </button>
                ))}
              </div>
            </details>
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
        {activeTab === "coordinates" && <CoordinatesTab brandId={brandId} />}
        {activeTab === LEARNINGS_TAB && (
          <LearningsTab
            brandId={brandId}
            state={learnings.state}
            onRetry={learnings.reload}
            highlightCampaignId={highlightCampaign}
          />
        )}

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
          {/* The brand onboarding (F42), same label as the 經營概況 title-row link (F42-I12); distinct from
              the 品牌資料 button next to it, which edits the brand profile. */}
          <Button asChild variant="outline">
            <Link to={`/brands/${encodeURIComponent(brandId)}/intake`}>品牌資料（建檔時填的）</Link>
          </Button>
          <Button variant="outline" onClick={() => setProfileOpen(true)} disabled={state.status !== "ready"}>品牌資料</Button>
        </>
      }/>
      {content}
    </div>
  );
}
