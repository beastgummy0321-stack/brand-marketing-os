import { lazy, Suspense, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import {
  CalendarDays,
  Eye,
  GripVertical,
  LayoutGrid,
  MousePointer2,
  Percent,
  Plus,
  RefreshCw,
  Settings2,
  Wallet,
} from "lucide-react";
import { useWorkspace } from "@/components/layout/WorkspaceContext";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/layout/ui/button";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import {
  defaultLayout,
  layoutKey,
  parseLayout,
  reorderWidgets,
  type DashboardView,
  type WidgetId,
} from "@/lib/dashboardLayout";
import { fetchMetaSpend } from "@/lib/metaApi";
import { formatMetaRoas, formatRelativeHours } from "@/lib/format";
import { LayoutEditor, metricLabels, widgetLabels } from "./LayoutEditor";
import {
  CampaignTable,
  InboxWidget,
  PerformanceWidget,
  SpendDistribution,
  number,
} from "./DashboardWidgets";
const CreativePerformanceSection = lazy(() =>
  import("./PerformanceDetails").then((m) => ({
    default: m.CreativePerformanceSection,
  })),
);
const MonthMoneySection = lazy(() =>
  import("./PerformanceDetails").then((m) => ({
    default: m.MonthMoneySection,
  })),
);

const icons = {
  spend: Wallet,
  impressions: Eye,
  clicks: MousePointer2,
  ctr: Percent,
  roas: LayoutGrid,
};
export function CockpitPage({ brandId }: { brandId: string }) {
  const { identity, scope, brands, brandsLoading, brandsError, refreshBrands } =
    useWorkspace();
  const brand = brands.find((b) => b.brand_id === brandId);
  const storageKey = layoutKey(identity.user.id, identity.org.id, brandId);
  const [layout, setLayout] = useState(() => {
    try {
      return parseLayout(localStorage.getItem(storageKey));
    } catch {
      return defaultLayout();
    }
  });
  const [saveError, setSaveError] = useState(false);
  const [editing, setEditing] = useState(false);
  const [params, setParams] = useSearchParams();
  const section = params.get("tab") === "analysis" ? "analysis" : "dashboard";
  function setSection(next: "dashboard" | "analysis") {
    setParams((previous) => {
      const result = new URLSearchParams(previous);
      if (next === "analysis") result.set("tab", next);
      else result.delete("tab");
      return result;
    });
  }

  const [dragging, setDragging] = useState<WidgetId | null>(null);
  const view =
    layout.views.find((v) => v.id === layout.activeId) ?? layout.views[0];
  const meta = useQuery({
    queryKey: [scope, brandId, "meta-spend"],
    queryFn: () => fetchMetaSpend(brandId),
    enabled: !!brand,
  });
  useEffect(() => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(layout));
      setSaveError(false);
    } catch {
      setSaveError(true);
    }
  }, [layout, storageKey]);
  function updateView(next: DashboardView) {
    setLayout((prev) => ({
      ...prev,
      views: prev.views.map((v) => (v.id === next.id ? next : v)),
    }));
  }
  function addView() {
    const next = {
      ...view,
      id: crypto.randomUUID(),
      name: `自訂檢視 ${layout.views.length}`,
    };
    setLayout((prev) => ({
      ...prev,
      activeId: next.id,
      views: [...prev.views, next],
    }));
    setEditing(true);
  }
  if (brandsLoading) return <Skeleton className="h-96" />;
  if (brandsError)
    return (
      <EmptyState
        title="品牌讀取失敗"
        description={brandsError}
        onAction={refreshBrands}
        actionLabel="重試"
      />
    );
  if (!brand)
    return (
      <EmptyState
        title="找不到這個品牌"
        description="請從品牌總覽選擇你有權限的品牌。"
        actionHref="/"
        actionInternal
        actionLabel="品牌總覽"
      />
    );
  const total = meta.data?.total;
  // F31-I03: 「尚未成功拉取」 only when nothing was ever read; rows read by another account's
  // pull or a backfill still say when they were read.
  const freshnessText = meta.data
    ? meta.data.last_pull_at
      ? `更新於 ${formatRelativeHours(meta.data.last_pull_at)}`
      : meta.data.data_pulled_at
        ? `資料讀取於 ${formatRelativeHours(meta.data.data_pulled_at)}`
        : "尚未成功拉取"
    : meta.isError
      ? "讀取失敗"
      : "讀取中…";
  const values = total
    ? {
        spend: number(total.spend),
        impressions: number(total.impressions),
        clicks: number(total.clicks),
        ctr:
          total.impressions > 0
            ? `${((total.clicks / total.impressions) * 100).toFixed(2)}%`
            : "—",
        roas: formatMetaRoas(total.roas),
      }
    : null;
  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="經營概況"
        description={brand.brand_name}
        actions={
          <>
            <Button asChild variant="outline">
              <Link to={`/brands/${encodeURIComponent(brandId)}/ads`}>
                前往投放中心
              </Link>
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                setSection("dashboard");
                setEditing(true);
              }}
            >
              <Settings2 />
              自訂版面
            </Button>
          </>
        }
      />
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-3">
        <div
          className="flex flex-wrap items-center gap-2"
          role="group"
          aria-label="看板檢視"
        >
          {layout.views.map((v) => (
            <Button
              key={v.id}
              variant={
                section === "dashboard" && v.id === view.id
                  ? "secondary"
                  : "ghost"
              }
              size="sm"
              aria-pressed={section === "dashboard" && v.id === view.id}
              onClick={() => {
                setSection("dashboard");
                setLayout((prev) => ({ ...prev, activeId: v.id }));
              }}
            >
              {v.name || "自訂檢視"}
            </Button>
          ))}
          <Button
            variant="ghost"
            size="sm"
            disabled={layout.views.length >= 8}
            onClick={() => {
              setSection("dashboard");
              addView();
            }}
          >
            <Plus />
            新增檢視
          </Button>
          <Button
            variant={section === "analysis" ? "secondary" : "ghost"}
            size="sm"
            aria-pressed={section === "analysis"}
            onClick={() => setSection("analysis")}
          >
            成效分析
          </Button>
        </div>
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <CalendarDays size={15} />
          <span>本月累計</span>
          <span className="h-4 border-l border-border" />
          <span>{freshnessText}</span>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="重新整理廣告數據"
            disabled={meta.isFetching}
            onClick={() => void meta.refetch()}
          >
            <RefreshCw className={meta.isFetching ? "animate-spin" : ""} />
          </Button>
        </div>
      </div>
      {section === "analysis" ? (
        <div className="surface p-6">
          <Suspense fallback={<Skeleton className="h-72" />}>
            <CreativePerformanceSection brandId={brandId} />
          </Suspense>
        </div>
      ) : (
        <>
          {saveError && (
            <p role="status" className="text-warning">
              瀏覽器無法儲存版面；本次操作仍會套用，重新整理後可能遺失。
            </p>
          )}
          {!!view.metrics.length && (
            <div className="dashboard-metrics">
              {view.metrics.map((id) => {
                const Icon = icons[id];
                return (
                  <article className="surface p-5" key={id}>
                    <div className="mb-4 flex items-center gap-2 text-xs text-muted-foreground">
                      <Icon size={16} />
                      {metricLabels[id]}
                    </div>
                    {meta.isPending ? (
                      <Skeleton className="h-8" />
                    ) : (
                      <p className="metric-number">{values?.[id] ?? "—"}</p>
                    )}
                    <p className="mt-3 text-xs text-muted-foreground">
                      {meta.isError
                        ? "資料讀取失敗"
                        : id === "ctr" && total?.impressions === 0
                          ? "尚無曝光，無法計算"
                          : id === "roas"
                            ? meta.data?.attribution_label
                              ? `平台回報 · 非全通路 · 歸因：${meta.data.attribution_label}`
                              : "平台回報 · 非全通路"
                            : "本月累計"}
                    </p>
                  </article>
                );
              })}
            </div>
          )}
          {meta.isError && (
            <div className="surface p-4" role="alert">
              廣告資料讀取失敗：{meta.error.message}
              <Button variant="link" onClick={() => void meta.refetch()}>
                重新載入
              </Button>
            </div>
          )}
          <div className="dashboard-grid">
            {view.widgets.map((w) => (
              <section
                key={w.id}
                className={`dashboard-widget surface ${dragging === w.id ? "widget-dragging" : ""}`}
                data-width={w.width}
                aria-label={widgetLabels[w.id]}
                onDragOver={(e) => {
                  if (dragging) e.preventDefault();
                }}
                onDrop={(e) => {
                  e.preventDefault();
                  if (dragging)
                    updateView(reorderWidgets(view, dragging, w.id));
                  setDragging(null);
                }}
              >
                <div className="absolute right-2 top-2 z-10 flex justify-end">
                  <button
                    type="button"
                    draggable
                    onDragStart={(e) => {
                      e.dataTransfer.effectAllowed = "move";
                      e.dataTransfer.setData("text/plain", w.id);
                      setDragging(w.id);
                    }}
                    onDragEnd={() => setDragging(null)}
                    onClick={() => setEditing(true)}
                    title="拖曳排序，或點擊調整版面"
                    aria-label={`調整${widgetLabels[w.id]}位置`}
                    className="rounded p-1 text-muted-foreground hover:bg-muted"
                  >
                    <GripVertical size={15} />
                  </button>
                </div>
                {w.id === "spend" &&
                  (meta.data ? (
                    <SpendDistribution data={meta.data} />
                  ) : (
                    <div className="p-6">
                      {meta.isPending ? (
                        <Skeleton className="h-64" />
                      ) : (
                        "活動花費分布暫時無法顯示"
                      )}
                    </div>
                  ))}
                {w.id === "campaigns" &&
                  (meta.data ? (
                    <CampaignTable data={meta.data} />
                  ) : (
                    <div className="p-6">
                      {meta.isPending ? (
                        <Skeleton className="h-48" />
                      ) : (
                        "活動資料暫時無法顯示"
                      )}
                    </div>
                  ))}
                {w.id === "performance" && (
                  <PerformanceWidget
                    brandId={brandId}
                    onDetails={() => setSection("analysis")}
                  />
                )}
                {w.id === "inbox" && <InboxWidget brandId={brandId} />}
                {w.id === "commerce" && (
                  <div className="p-5">
                    <Suspense fallback={<Skeleton className="h-48" />}>
                      <MonthMoneySection brandId={brandId} />
                    </Suspense>
                  </div>
                )}
              </section>
            ))}
          </div>
        </>
      )}
      {editing && (
        <LayoutEditor
          view={view}
          onChange={updateView}
          onClose={() => setEditing(false)}
          onReset={() =>
            updateView({
              ...defaultLayout().views[0],
              id: view.id,
              name: view.name,
            })
          }
          canDelete={layout.views.length > 1}
          onDelete={() => {
            const views = layout.views.filter((v) => v.id !== view.id);
            setLayout({ version: 1, views, activeId: views[0].id });
            setEditing(false);
          }}
        />
      )}
    </div>
  );
}
