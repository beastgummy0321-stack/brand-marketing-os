import { useCallback, useEffect, useState } from "react";
import { useLocation, useSearchParams } from "react-router-dom";
import { PageHeader } from "@/components/layout/PageHeader";
import { PageTabs } from "@/components/layout/PageTabs";
import { EmptyState } from "@/components/layout/EmptyState";
import { Badge } from "@/components/layout/ui/badge";
import { useWorkspace } from "@/components/layout/WorkspaceContext";
import { getCampaign, type CampaignDetail } from "@/lib/adsApi";
import { STATUS_LABEL, STATUS_TONE } from "./AdsHomePage";
import { OverviewTab } from "./OverviewTab";
import { StrategyTab } from "./StrategyTab";
import { DeliveryTab } from "./DeliveryTab";
import { AssetsTab } from "./AssetsTab";

type WorkspaceTab = "overview" | "strategy" | "structure" | "assets" | "performance";

const TABS: { value: WorkspaceTab; label: string }[] = [
  { value: "overview", label: "總覽" },
  { value: "strategy", label: "策略" },
  { value: "structure", label: "投放結構" },
  { value: "assets", label: "素材" },
  { value: "performance", label: "成效" },
];

function periodLabel(c: CampaignDetail): string {
  return c.start_date && c.end_date ? `${c.start_date} ~ ${c.end_date}` : "投放期間尚未設定";
}

/** Campaign 五分頁工作區（F03-I14／I15）：總覽／策略／投放結構／素材四分頁是真的內容；
 * 成效還沒補（自己的票補上），先用「誠實的空狀態＋下一步」頂著——
 * 規則沿用 §4.2：分頁沒資料不做成禁用分頁。 */
export function CampaignWorkspace({
  brandId,
  campaignId,
}: {
  brandId: string;
  campaignId: string;
}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation() as { state?: { parseWarning?: string } };
  const tabParam = (searchParams.get("tab") as WorkspaceTab | null) ?? "overview";
  const tab = TABS.some((t) => t.value === tabParam) ? tabParam : "overview";
  const { brands } = useWorkspace();
  const brandName = brands.find((b) => b.brand_id === brandId)?.brand_name ?? brandId;

  const [state, setState] = useState<
    { status: "loading" } | { status: "error"; message: string } | { status: "ready"; campaign: CampaignDetail }
  >({ status: "loading" });

  const load = useCallback(() => {
    setState({ status: "loading" });
    getCampaign(brandId, campaignId)
      .then((campaign) => setState({ status: "ready", campaign }))
      .catch((err: unknown) =>
        setState({
          status: "error",
          message: err instanceof Error ? err.message : "讀取 Campaign 失敗，請稍後再試。",
        }),
      );
  }, [brandId, campaignId]);

  useEffect(load, [load]);

  function changeTab(next: WorkspaceTab) {
    // 保留其他查詢參數——占位骨架的 setSearchParams({tab}) 會把它們沖掉。
    setSearchParams((prev) => {
      const params = new URLSearchParams(prev);
      params.set("tab", next);
      return params;
    });
  }

  const campaign = state.status === "ready" ? state.campaign : null;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title={campaign ? campaign.name : "Campaign"}
        description={campaign ? `${brandName} ・ ${periodLabel(campaign)}` : undefined}
        actions={
          campaign ? <Badge variant={STATUS_TONE[campaign.status]}>{STATUS_LABEL[campaign.status]}</Badge> : undefined
        }
      />
      {location.state?.parseWarning && (
        <p className="text-sm text-warning">{location.state.parseWarning}</p>
      )}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <PageTabs items={TABS} value={tab} onChange={changeTab} label="Campaign 工作區分頁" />
        {campaign && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <span>{periodLabel(campaign)}</span>
            <Badge variant="outline">● Meta</Badge>
          </div>
        )}
      </div>
      {state.status === "error" ? (
        <EmptyState title="讀取失敗" description={state.message} onAction={load} actionLabel="重新載入" />
      ) : !campaign ? (
        <div className="surface">
          <div className="surface-body py-10 text-center text-sm text-muted-foreground">讀取中…</div>
        </div>
      ) : tab === "overview" ? (
        <OverviewTab campaign={campaign} onChangeTab={changeTab} />
      ) : tab === "strategy" ? (
        <StrategyTab
          brandId={brandId}
          campaign={campaign}
          onCampaignChange={(next) => setState({ status: "ready", campaign: next })}
        />
      ) : tab === "structure" ? (
        <DeliveryTab
          brandId={brandId}
          campaign={campaign}
          onCampaignChange={(next) => setState({ status: "ready", campaign: next })}
        />
      ) : tab === "assets" ? (
        <AssetsTab
          brandId={brandId}
          campaign={campaign}
          onCampaignChange={(next) => setState({ status: "ready", campaign: next })}
        />
      ) : (
        <EmptyState
          title={`${TABS.find((t) => t.value === tab)?.label}還沒做`}
          description="這個分頁的內容由後續票補上。"
        />
      )}
    </div>
  );
}
