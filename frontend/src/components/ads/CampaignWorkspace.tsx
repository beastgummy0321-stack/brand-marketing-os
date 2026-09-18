import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useSearchParams } from "react-router-dom";
import { PageHeader } from "@/components/layout/PageHeader";
import { PageTabs } from "@/components/layout/PageTabs";
import { EmptyState } from "@/components/layout/EmptyState";
import { Badge } from "@/components/layout/ui/badge";
import { Button } from "@/components/layout/ui/button";
import { useWorkspace } from "@/components/layout/WorkspaceContext";
import { getCampaign, type AdapterKey, type CampaignDetail } from "@/lib/adsApi";
import { fetchChannels, type Channel } from "@/lib/adsLaunchApi";
import { completeExternalView, syncCampaign, syncJob } from "@/lib/adsExternalApi";
import { STATUS_LABEL, STATUS_TONE } from "./AdsHomePage";
import { OverviewTab } from "./OverviewTab";
import { StrategyTab } from "./StrategyTab";
import { DeliveryTab } from "./DeliveryTab";
import { AssetsTab } from "./AssetsTab";
import { PerformanceTab } from "./PerformanceTab";
import { PublishPage } from "./PublishPage";
import { ChangeControl } from "./ChangeControl";
import type { StepTarget, WorkspaceTab } from "./nextStep";
import { formatSyncTime } from "@/lib/format";

const TABS: { value: WorkspaceTab; label: string }[] = [
  { value: "overview", label: "總覽" },
  { value: "strategy", label: "策略" },
  { value: "structure", label: "投放結構" },
  { value: "assets", label: "素材" },
  { value: "performance", label: "成效" },
  { value: "changes", label: "變更與核對" },
];

function periodLabel(c: CampaignDetail): string {
  if (c.origin === "imported") {
    const root = c.external_view?.entities.find(e => !e.parent_native_id);
    return `${root?.start_date ?? "開始日未知"} ~ ${root?.end_date ?? "結束日未知"}`;
  }
  return c.start_date && c.end_date ? `${c.start_date} ~ ${c.end_date}` : "投放期間尚未設定";
}

/** Campaign 五分頁工作區（F03-I14／I15）：總覽／策略／投放結構／素材四分頁是真的內容；
 * 成效還沒補（自己的票補上），先用「誠實的空狀態＋下一步」頂著——
 * 規則沿用 §4.2：分頁沒資料不做成禁用分頁。 */
function Workspace({
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
  const request = useRef<AbortController | null>(null);
  const [syncId, setSyncId] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState("");
  const lifetime = useRef(new AbortController());
  useEffect(() => {
    lifetime.current = new AbortController();
    return () => { lifetime.current.abort(); request.current?.abort(); };
  }, []);

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
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setState({ status: "loading" });
    getCampaign(brandId, campaignId)
      .then(async (campaign) => {
        if (controller.signal.aborted) return;
        const hydrated = campaign.origin === "imported"
          ? { ...campaign, external_view: await completeExternalView(brandId, campaignId, controller.signal) }
          : campaign;
        if (!controller.signal.aborted) setState({ status: "ready", campaign: hydrated });
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) setState({
          status: "error",
          message: err instanceof Error ? err.message : "讀取 Campaign 失敗，請稍後再試。",
        });
      });
  }, [brandId, campaignId]);

  useEffect(load, [load]);

  async function refreshPlatform() {
    if (syncing) return;
    const signal = lifetime.current.signal;
    setSyncing(true); setSyncError("");
    try {
      const result = await syncCampaign(brandId, campaignId);
      if (!signal.aborted) setSyncId(result.job.id);
    } catch (err) {
      if (!signal.aborted) { setSyncError(err instanceof Error ? err.message : "同步失敗。"); setSyncing(false); }
    }
  }
  useEffect(() => {
    if (!syncId) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const result = await syncJob(brandId, syncId!, controller.signal);
        if (controller.signal.aborted) return;
        if (["pending", "running"].includes(result.job.status)) timer = setTimeout(() => void poll(), 3000);
        else {
          setSyncId(null); setSyncing(false);
          if (result.job.error) setSyncError(result.job.error);
          load();
        }
      } catch (err) {
        if (!controller.signal.aborted) { setSyncError(err instanceof Error ? err.message : "同步狀態讀取失敗。"); setSyncId(null); setSyncing(false); }
      }
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [syncId, brandId, load]);

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
    if (target === "publish") { if (canPublish) setPublishAdapter("auto_meta"); else changeTab("assets"); }
    else changeTab(target);
  }

  const campaign = state.status === "ready" ? state.campaign : null;
  const lastRead = Object.values(campaign?.external_view?.sync ?? {}).map(s => s.last_success_at).filter((value): value is string => Boolean(value)).sort().at(-1);
  const nativeStatus = campaign?.external_view?.entities.find(e => !e.parent_native_id)?.native_status;
  const platformState = ({ ACTIVE: "活動設定：啟用", PAUSED: "活動設定：暫停", ARCHIVED: "活動設定：已封存", DELETED: "活動設定：已刪除" } as Record<string, string>)[nativeStatus ?? ""] ?? "活動設定尚待確認";
  // 已經投放中／結束／結案不再需要發布動作——只在草稿／待發布時給這個入口。
  const canPublish = campaign ? campaign.origin !== "imported" && !campaign.capabilities?.unavailable.publish && (campaign.status === "draft" || campaign.status === "ready") : false;

  function updateCampaign(next: CampaignDetail) {
    setState(previous => ({ status: "ready", campaign: {
      ...next, external_view: next.origin === "imported" && previous.status === "ready" ? previous.campaign.external_view : next.external_view,
    } }));
  }

  return (
    <div className="flex flex-col gap-4">
      {campaign?.simulation_mode && <p role="status" className="rounded-md bg-warning/10 p-3 text-sm">隔離模擬品牌：成效與學習只供演練，不代表真實投放。</p>}
      <PageHeader
        title={campaign ? campaign.name : "Campaign"}
        description={campaign ? `${brandName} ・ ${periodLabel(campaign)}` : undefined}
        actions={
          campaign ? (
            <div className="flex items-center gap-2">
              <Badge variant={STATUS_TONE[campaign.status]}>{campaign.origin === "imported" ? platformState : STATUS_LABEL[campaign.status]}</Badge>
              {campaign.origin === "imported" && <Button size="sm" variant="outline" disabled={syncing} onClick={() => void refreshPlatform()}>{syncing ? "同步中…" : "重新讀取平台"}</Button>}
              {canPublish && (
                <Button size="sm" onClick={() => setPublishAdapter("auto_meta")}>
                  選擇上架方式
                </Button>
              )}
            </div>
          ) : undefined
        }
      />
      {syncError && <p role="alert" className="text-sm text-destructive">{syncError}</p>}
      {campaign?.origin === "imported" && <p className="text-xs text-muted-foreground">
        {campaign.external_view?.connections.map(connection => `${connection.platform === "meta" ? "Meta" : connection.platform} · ${connection.source_account} · ${connection.state === "connected" ? "已連線" : "連線中斷，保留歷史"}`).join("；")}
        {" · 最近成功："}{lastRead ? formatSyncTime(lastRead) : "尚未成功讀回"}
        {" · 活動設定不代表已實際投遞"}
        {Object.entries(campaign.external_view?.sync ?? {}).filter(([, value]) => value.error || value.error_code).map(([section, value]) => <span className="text-warning" key={section}> · {section}：{value.error ?? value.error_code}</span>)}
      </p>}
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
          ) : tab === "changes" ? (
            <ChangeControl brandId={brandId} campaignId={campaign.id} />
          ) : (
            <PerformanceTab brandId={brandId} campaign={campaign} onCampaignChange={updateCampaign} onChangeTab={go} onSync={() => void refreshPlatform()} syncing={syncing} />
          )}
        </>
      )}
    </div>
  );
}

export function CampaignWorkspace(props: Parameters<typeof Workspace>[0]) { return <Workspace key={`${props.brandId}:${props.campaignId}`} {...props} />; }
