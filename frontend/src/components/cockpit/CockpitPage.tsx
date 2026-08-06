import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { AlertsPanel } from "@/components/cockpit/AlertsPanel";
import { CampaignStageBadge } from "@/components/cockpit/CampaignStageBadge";
import { CockpitChart } from "@/components/cockpit/CockpitChart";
import { ContentPipelineSummary } from "@/components/cockpit/ContentPipelineSummary";
import { FuelGauge } from "@/components/cockpit/FuelGauge";
import { GuideCards } from "@/components/cockpit/GuideCards";
import { KpiCard } from "@/components/cockpit/KpiCard";
import { LastSyncBadge } from "@/components/cockpit/LastSyncBadge";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { fetchCockpit, type CockpitData } from "@/lib/api";
import { formatCount, formatCurrency, formatRoas } from "@/lib/format";
import { hasSeenCockpitTour, runCockpitTour } from "@/lib/tour";

/** 單品牌駕駛艙第一屏（票 03/05）：四張 KPI 卡＋營收 vs 花費疊線主圖＋下一步指南卡／
 * 異常警示區並排＋窄條（AI 油錢錶／內容產線小計）。品牌由路徑參數 `/brands/:brandId`
 * 決定（票 05-spa-routing），呼叫端在 App.tsx 用 `useParams` 取出後傳進來，
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

  // 首次進駕駛艙自動跑一次 30 秒重點導覽（票 09，規格使用者故事 20）；資料就緒後才跑，
  // 不然 KPI／指南卡／警示區的 data-tour 元素還沒掛上去，driver.js 會找不到目標。
  useEffect(() => {
    if (state.status === "ready" && !hasSeenCockpitTour()) {
      runCockpitTour();
    }
  }, [state.status]);

  const breadcrumb = (
    <Breadcrumb
      items={[
        { label: "跨品牌總覽", href: "/" },
        { label: state.status === "ready" ? state.data.brand_name : "品牌駕駛艙" },
      ]}
    />
  );

  let content: ReactNode;
  if (state.status === "loading") {
    content = <EmptyState title="讀取中…" description="正在載入這個品牌的駕駛艙資料。" />;
  } else if (state.status === "error") {
    content = (
      <EmptyState
        title="讀取失敗"
        description={state.message}
        actionHref="/"
        actionInternal
        actionLabel="回跨品牌總覽"
      />
    );
  } else {
    const { data } = state;
    content = (
      <div className="flex flex-col gap-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h1 className="font-display text-2xl text-foreground">{data.brand_name}</h1>
            <CampaignStageBadge stage={data.campaign_stage} />
            <LastSyncBadge lastSyncAt={data.last_sync_at} stale={data.data_stale} />
          </div>
          <div className="flex items-center gap-4">
            <button
              type="button"
              onClick={runCockpitTour}
              className="text-sm font-medium text-primary underline-offset-4 hover:underline"
            >
              重新導覽
            </button>
            <Link
              to="/"
              className="text-sm font-medium text-primary underline-offset-4 hover:underline"
            >
              回跨品牌總覽
            </Link>
          </div>
        </div>

        <div data-tour="kpis" className="grid grid-cols-4 gap-4">
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

  return (
    <div className="flex flex-col gap-4">
      {breadcrumb}
      {content}
    </div>
  );
}
