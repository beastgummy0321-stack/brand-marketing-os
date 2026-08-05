import { useCallback, useEffect, useState } from "react";
import { AlertsPanel } from "@/components/cockpit/AlertsPanel";
import { CockpitChart } from "@/components/cockpit/CockpitChart";
import { ContentPipelineSummary } from "@/components/cockpit/ContentPipelineSummary";
import { FuelGauge } from "@/components/cockpit/FuelGauge";
import { GuideCards } from "@/components/cockpit/GuideCards";
import { KpiCard } from "@/components/cockpit/KpiCard";
import { EmptyState } from "@/components/layout/EmptyState";
import { fetchCockpit, type CockpitData } from "@/lib/api";
import { formatCount, formatCurrency, formatRoas } from "@/lib/format";

/** 單品牌駕駛艙第一屏（票 03/05）：四張 KPI 卡＋營收 vs 花費疊線主圖＋下一步指南卡／
 * 異常警示區並排＋窄條（AI 油錢錶／內容產線小計）。由 `?brand=` 查詢字串決定品牌，
 * 見 App.tsx／BrandCard.tsx 的路由筆記。 */
type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: CockpitData };

export function CockpitPage({ brandId }: { brandId: string }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  const load = useCallback(() => {
    let cancelled = false;
    setState((prev) => (prev.status === "ready" ? prev : { status: "loading" }));
    fetchCockpit(brandId)
      .then((data) => {
        if (!cancelled) setState({ status: "ready", data });
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
  }, [brandId]);

  useEffect(() => load(), [load]);

  if (state.status === "loading") {
    return <EmptyState title="讀取中…" description="正在載入這個品牌的駕駛艙資料。" />;
  }
  if (state.status === "error") {
    return (
      <EmptyState
        title="讀取失敗"
        description={state.message}
        actionHref="/app/"
        actionLabel="回跨品牌總覽"
      />
    );
  }

  const { data } = state;
  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="font-display text-2xl text-foreground">{data.brand_name}</h1>
        <a
          href="/app/"
          className="text-sm font-medium text-primary underline-offset-4 hover:underline"
        >
          回跨品牌總覽
        </a>
      </div>

      <div className="grid grid-cols-4 gap-4">
        <KpiCard label="本月營收" kpi={data.kpis.revenue} format={formatCurrency} />
        <KpiCard label="廣告花費" kpi={data.kpis.spend} format={formatCurrency} />
        <KpiCard label="ROAS" kpi={data.kpis.roas} format={formatRoas} />
        <KpiCard label="訂單數" kpi={data.kpis.orders} format={formatCount} />
      </div>

      <CockpitChart chart={data.chart} />

      <div className="grid grid-cols-2 gap-4">
        <GuideCards cards={data.guide_cards} />
        <AlertsPanel alerts={data.alerts} onResolved={load} />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <FuelGauge gauge={data.fuel_gauge} />
        <ContentPipelineSummary pipeline={data.content_pipeline} />
      </div>
    </div>
  );
}
