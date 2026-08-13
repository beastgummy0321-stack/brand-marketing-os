import { useCallback, useEffect, useState } from "react";
import { FluidCard } from "@/components/layout/FluidCard";
import { Skeleton } from "@/components/layout/Skeleton";
import {
  fetchPerformanceView,
  fetchPinnedViews,
  savePinnedViews,
  type DashboardPerformanceView,
  type PinnedViewCatalogItem,
  type PinnedViewKey,
} from "@/lib/pinnedViewsApi";
import { cn } from "@/lib/utils";
import { NoCycleContent, PinnedViewContent } from "./PinnedViewContent";
import { PinManageMenu } from "./PinManageMenu";

type ConfigState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; catalog: PinnedViewCatalogItem[]; pinned: PinnedViewKey[] };

type ViewState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: DashboardPerformanceView | null };

/** 駕駛艙成效釘選區（S3P，契約 `.scratch/grill/GRILL-B4R-performance.md` 第一節）：頂部
 * chips 列（釘選視圖，依目錄固定順序，最多 5 顆）＋「管理視圖」下拉勾選＋下方切換內容。
 * 插在既有 KPI 卡列之下、`CockpitChart` 之上（`CockpitPage.tsx` 唯一新增的一行），駕駛艙
 * 其餘既有卡片不動一行（R1-1 依賴邊：迴歸驗收既有卡片）。 */
export function PerformancePins({ brandId }: { brandId: string }) {
  const [config, setConfig] = useState<ConfigState>({ status: "loading" });
  const [selectedKey, setSelectedKey] = useState<PinnedViewKey | null>(null);
  const [viewState, setViewState] = useState<ViewState>({ status: "loading" });
  const [savingKey, setSavingKey] = useState<PinnedViewKey | null>(null);
  const [errorByKey, setErrorByKey] = useState<Partial<Record<PinnedViewKey, string>>>({});

  const loadConfig = useCallback(() => {
    setConfig({ status: "loading" });
    fetchPinnedViews(brandId)
      .then(({ catalog, pinned }) => {
        setConfig({ status: "ready", catalog, pinned });
        setSelectedKey((prev) => (prev && pinned.includes(prev) ? prev : (pinned[0] ?? null)));
      })
      .catch((err: unknown) => setConfig({ status: "error", message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。" }));
  }, [brandId]);

  useEffect(loadConfig, [loadConfig]);

  const loadView = useCallback(
    (key: PinnedViewKey) => {
      setViewState({ status: "loading" });
      fetchPerformanceView(brandId, key)
        .then((data) => setViewState({ status: "ready", data }))
        .catch((err: unknown) => setViewState({ status: "error", message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。" }));
    },
    [brandId],
  );

  useEffect(() => {
    if (selectedKey) loadView(selectedKey);
  }, [selectedKey, loadView]);

  async function handleToggle(key: PinnedViewKey) {
    if (config.status !== "ready") return;
    const next = config.pinned.includes(key) ? config.pinned.filter((k) => k !== key) : [...config.pinned, key];
    setSavingKey(key);
    setErrorByKey((prev) => ({ ...prev, [key]: undefined }));
    try {
      const updated = await savePinnedViews(brandId, next);
      setConfig({ status: "ready", catalog: updated.catalog, pinned: updated.pinned });
      setSelectedKey((prev) => (prev && updated.pinned.includes(prev) ? prev : (updated.pinned[0] ?? null)));
    } catch (err) {
      setErrorByKey((prev) => ({ ...prev, [key]: err instanceof Error ? err.message : "操作失敗，請稍後再試。" }));
    } finally {
      setSavingKey(null);
    }
  }

  if (config.status === "loading") {
    return (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-7 w-64" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }
  if (config.status === "error") {
    return (
      <div className="rounded-[var(--radius-xl)] border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
        讀取失敗，請稍後再試。
        <button type="button" onClick={loadConfig} className="ml-2 font-medium text-primary hover:underline">
          重新載入
        </button>
      </div>
    );
  }

  const displayedChips = config.catalog.filter((c) => config.pinned.includes(c.key));

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        {displayedChips.map((chip) => (
          <button
            key={chip.key}
            type="button"
            onClick={() => setSelectedKey(chip.key)}
            className={cn(
              "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
              selectedKey === chip.key
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border text-muted-foreground hover:border-primary hover:text-primary",
            )}
          >
            {chip.label}
          </button>
        ))}
        <PinManageMenu catalog={config.catalog} pinned={config.pinned} savingKey={savingKey} errorByKey={errorByKey} onToggle={handleToggle} />
      </div>

      <FluidCard>
        {viewState.status === "loading" && <Skeleton className="h-40 w-full" />}
        {viewState.status === "error" && (
          <div className="py-6 text-center text-sm text-muted-foreground">
            讀取失敗，請稍後再試。
            <button type="button" onClick={() => selectedKey && loadView(selectedKey)} className="ml-2 font-medium text-primary hover:underline">
              重新載入
            </button>
          </div>
        )}
        {viewState.status === "ready" &&
          (viewState.data === null ? <NoCycleContent brandId={brandId} /> : <PinnedViewContent brandId={brandId} view={viewState.data} onRefresh={() => selectedKey && loadView(selectedKey)} />)}
      </FluidCard>
    </div>
  );
}
