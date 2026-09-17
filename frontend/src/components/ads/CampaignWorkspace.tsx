import { useCallback, useEffect, useState } from "react";
import { useLocation, useSearchParams } from "react-router-dom";
import { PageHeader } from "@/components/layout/PageHeader";
import { PageTabs } from "@/components/layout/PageTabs";
import { EmptyState } from "@/components/layout/EmptyState";
import { Badge } from "@/components/layout/ui/badge";
import { Button } from "@/components/layout/ui/button";
import { useWorkspace } from "@/components/layout/WorkspaceContext";
import { getCampaign, type AdapterKey, type CampaignDetail } from "@/lib/adsApi";
import { fetchChannels, type Channel } from "@/lib/adsLaunchApi";
import { STATUS_LABEL, STATUS_TONE } from "./AdsHomePage";
import { OverviewTab } from "./OverviewTab";
import { StrategyTab } from "./StrategyTab";
import { DeliveryTab } from "./DeliveryTab";
import { AssetsTab } from "./AssetsTab";
import { PerformanceTab } from "./PerformanceTab";
import { PublishPage } from "./PublishPage";
import type { StepTarget, WorkspaceTab } from "./nextStep";

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
  const [publishAdapter, setPublishAdapter] = useState<AdapterKey | null>(null);
  const [channels, setChannels] = useState<Channel[]>([]);

  useEffect(() => {
    let cancelled = false;
    fetchChannels(brandId)
      .then((rows) => {
        if (!cancelled) setChannels(rows);
      })
      .catch(() => {
        /* 靜默：讀失敗就不印通路徽章，不是整頁壞掉 */
      });
    return () => {
      cancelled = true;
    };
  }, [brandId]);

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

  // §6.2 決議 15：規則回的 target 可能是 "publish"，不是分頁——這裡把它接到既有的發布入口。
  function go(target: StepTarget) {
    if (target === "publish") setPublishAdapter("auto_meta");
    else changeTab(target);
  }

  const campaign = state.status === "ready" ? state.campaign : null;
  // 已經投放中／結束／結案不再需要發布動作——只在草稿／待發布時給這個入口。
  const canPublish = campaign ? campaign.status === "draft" || campaign.status === "ready" : false;

  function updateCampaign(next: CampaignDetail) {
    setState({ status: "ready", campaign: next });
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title={campaign ? campaign.name : "Campaign"}
        description={campaign ? `${brandName} ・ ${periodLabel(campaign)}` : undefined}
        actions={
          campaign ? (
            <div className="flex items-center gap-2">
              <Badge variant={STATUS_TONE[campaign.status]}>{STATUS_LABEL[campaign.status]}</Badge>
              {canPublish && (
                <Button size="sm" onClick={() => setPublishAdapter("auto_meta")}>
                  選擇上架方式
                </Button>
              )}
            </div>
          ) : undefined
        }
      />
      {location.state?.parseWarning && (
        <p className="text-sm text-warning">{location.state.parseWarning}</p>
      )}
      {campaign && publishAdapter ? (
        <PublishPage
          brandId={brandId}
          campaign={campaign}
          adapter={publishAdapter}
          onCampaignChange={updateCampaign}
          onClose={() => setPublishAdapter(null)}
          onViewPerformance={() => {
            setPublishAdapter(null);
            changeTab("performance");
          }}
          onChangeAdapter={setPublishAdapter}
          onGoToAssets={() => {
            setPublishAdapter(null);
            changeTab("assets");
          }}
        />
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <PageTabs items={TABS} value={tab} onChange={changeTab} label="Campaign 工作區分頁" />
            {campaign && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <span>{periodLabel(campaign)}</span>
                {campaign.groups[0] && (
                  <Badge variant="outline">
                    ●{" "}
                    {channels.find((c) => c.key === campaign.groups[0].channel_key)?.label
                      ?? campaign.groups[0].channel_key}
                  </Badge>
                )}
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
            <OverviewTab campaign={campaign} onChangeTab={go} />
          ) : tab === "strategy" ? (
            <StrategyTab
              brandId={brandId}
              campaign={campaign}
              onCampaignChange={updateCampaign}
              onChangeTab={go}
            />
          ) : tab === "structure" ? (
            <DeliveryTab brandId={brandId} campaign={campaign} onCampaignChange={updateCampaign} onChangeTab={go} />
          ) : tab === "assets" ? (
            <AssetsTab brandId={brandId} campaign={campaign} onCampaignChange={updateCampaign} onChangeTab={go} />
          ) : (
            <PerformanceTab brandId={brandId} campaign={campaign} onCampaignChange={updateCampaign} onChangeTab={go} />
          )}
        </>
      )}
    </div>
  );
}
