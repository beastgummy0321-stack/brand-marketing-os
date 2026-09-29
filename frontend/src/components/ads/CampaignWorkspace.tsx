import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Navigate, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { getCampaign, type CampaignDetail } from "@/lib/adsApi";
import { completeExternalView, syncCampaign, syncJob } from "@/lib/adsExternalApi";
import { getCampaignWorkspace } from "@/lib/adsWorkspaceApi";
import { useApiRead } from "@/lib/useApiRead";
import { OverviewTab } from "./OverviewTab";
import { StrategyTab } from "./StrategyTab";
import { DeliveryTab } from "./DeliveryTab";
import { AssetsTab } from "./AssetsTab";
import { PerformanceTab } from "./PerformanceTab";
import { ChangeControl } from "./ChangeControl";
import { ReviewPanel } from "./ReviewPanel";
import { CampaignPerfBody } from "./detail/CampaignDetailPage";
import { OverviewBody, capOf } from "./workspace/OverviewBody";
import { WORKSPACE_TABS, WorkspaceHead, isDraftCampaign } from "./workspace/WorkspaceHead";
import { ActionBar, Disclosure, ResultHero, TargetRuler } from "./patterns";
import { Button } from "@/components/layout/ui/button";
import type { StepTarget, WorkspaceTab } from "./nextStep";

/** Everything a tab body gets from the workspace. The structure, assets and changes tabs are slots: their own issues
 * rebuild the component mounted there (`DeliveryTab`, `AssetsTab`, `ChangeControl`) without editing this file. */
export interface TabSlotProps {
  brandId: string;
  campaign: CampaignDetail;
  onCampaignChange: (campaign: CampaignDetail) => void;
  onChangeTab: (target: StepTarget) => void;
}

const SLOTS: Record<"structure" | "assets" | "changes", (p: TabSlotProps) => ReactNode> = {
  structure: (p) => <DeliveryTab {...p} />,
  assets: (p) => <AssetsTab {...p} />,
  changes: (p) => <ChangeControl brandId={p.brandId} campaignId={p.campaign.id} />,
};

/** v10 (F30-I07) campaign workspace (prototype `campPage()`): the head (`WorkspaceHead`: chips, stage rail, tabs
 * with the open-decision count) over one tab body. 總覽 is `OverviewBody` (draft／gap／live from `GET …/workspace`,
 * the old overview folded under 進階); 成效 (`perf`) is the F29 detail body (F40-I06: with the 這期狀態列 on top, fed the
 * campaign and the platform read) with the old review and platform charts folded under 「進階：每日資料、次要指標與舊版
 * 檢討」. `?tab=performance` and `/detail` land on `perf`. The campaign itself and the
 * workspace progress are two reads that fail independently. */
function Workspace({ brandId, campaignId }: { brandId: string; campaignId: string }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation() as { pathname: string; state?: { parseWarning?: string } };
  const tabParam = searchParams.get("tab");
  const tab: WorkspaceTab = WORKSPACE_TABS.some((t) => t.value === tabParam) ? tabParam as WorkspaceTab : "overview";

  const [state, setState] = useState<
    { status: "loading" } | { status: "error"; message: string } | { status: "ready"; campaign: CampaignDetail }
  >({ status: "loading" });
  const workspace = useApiRead((signal) => getCampaignWorkspace(brandId, campaignId, signal), [brandId, campaignId]);
  const navigate = useNavigate();
  const request = useRef<AbortController | null>(null);
  const [syncId, setSyncId] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState("");
  const lifetime = useRef(new AbortController());
  useEffect(() => {
    lifetime.current = new AbortController();
    return () => { lifetime.current.abort(); request.current?.abort(); };
  }, []);

  // `quiet`: the reload after a platform read keeps the current body mounted (an open close dialog
  // or opened fold survives it; F37 — the dialog re-enables 確認結案 once the read ends).
  const load = useCallback((quiet = false) => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    if (!quiet) setState({ status: "loading" });
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

  useEffect(() => load(), [load]);

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
  const reloadWorkspace = workspace.reload;
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
          load(true);
          reloadWorkspace();
        }
      } catch (err) {
        if (!controller.signal.aborted) { setSyncError(err instanceof Error ? err.message : "同步狀態讀取失敗。"); setSyncId(null); setSyncing(false); }
      }
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [syncId, brandId, load, reloadWorkspace]);

  function changeTab(next: WorkspaceTab) {
    // Keep the other query parameters (a bare setSearchParams({tab}) would drop them).
    setSearchParams((prev) => {
      const params = new URLSearchParams(prev);
      params.set("tab", next);
      return params;
    });
  }

  const campaign = state.status === "ready" ? state.campaign : null;
  const ws = workspace.status === "ready" ? workspace.data : null;
  // Only a campaign not on a platform yet gets the publish page.
  const canPublish = campaign ? campaign.origin !== "imported" && !campaign.capabilities?.unavailable.publish && (campaign.status === "draft" || campaign.status === "ready") : false;

  // §6.2 decision 15: a step target may be "publish" — the publish page at its own URL (F30-I13), which lands on the
  // step its launch reports; "performance" is the old perf key.
  function go(target: StepTarget) {
    if (target === "publish") { if (canPublish) navigate(`/brands/${encodeURIComponent(brandId)}/ads/campaigns/${encodeURIComponent(campaignId)}/publish`); else changeTab("assets"); }
    else changeTab(target === "performance" ? "perf" : target);
  }

  function updateCampaign(next: CampaignDetail) {
    setState(previous => ({ status: "ready", campaign: {
      ...next, external_view: next.origin === "imported" && previous.status === "ready" ? previous.campaign.external_view : next.external_view,
    } }));
    reloadWorkspace();
  }

  if (tabParam === "performance") {
    const params = new URLSearchParams(searchParams);
    params.set("tab", "perf");
    return <Navigate replace to={`${location.pathname}?${params.toString()}`} />;
  }

  const slot: TabSlotProps | null = campaign ? { brandId, campaign, onCampaignChange: updateCampaign, onChangeTab: go } : null;
  const platformSync = { onSync: () => void refreshPlatform(), syncing, error: syncError };
  let body: ReactNode = null;
  if (state.status === "error") {
    body = <EmptyState title="讀取失敗" description={state.message} onAction={() => load()} actionLabel="重新載入" />;
  } else if (!campaign || !slot) {
    body = <Skeleton className="h-60 w-full" />;
  } else if (tab === "overview") {
    const advanced = <OverviewTab campaign={campaign} onChangeTab={go} platformSync={campaign.origin === "imported" ? platformSync : undefined} />;
    body = ws
      ? <OverviewBody brandId={brandId} campaign={campaign} workspace={ws} canPublish={canPublish} onGo={go} advanced={advanced} />
      : workspace.status === "loading" ? <Skeleton className="h-60 w-full" />
      // The head already shows the progress read's failure with 重試; the folded overview stays reachable.
      : <Disclosure label="進階：更多活動資訊">{advanced}</Disclosure>;
  } else if (tab === "strategy") {
    body = (
      <StrategyTab {...slot}
        launchApproved={ws ? ws.stage.key === "launch" || (ws.draft?.launch_total ?? 0) > 0 : null}
        onLaunchSettingsSaved={reloadWorkspace} />
    );
  } else if (tab === "perf") {
    // The old review panel and platform charts (incl. the comparison plan and simulation tools) stay reachable on a
    // draft too — folded, never deleted.
    const advanced = (
      <Disclosure label="進階：每日資料、次要指標與舊版檢討" defaultOpen={searchParams.has("ad") || searchParams.has("review")}>
        <div className="flex flex-col gap-4">
          <ReviewPanel brandId={brandId} campaignId={campaign.id} onGoal={() => changeTab("strategy")} />
          <PerformanceTab {...slot} onSync={() => void refreshPlatform()} syncing={syncing} syncError={syncError} />
        </div>
      </Disclosure>
    );
    body = isDraftCampaign(campaign, ws)
      ? <DraftPerf brandId={brandId} campaign={campaign} onGo={go} advanced={advanced} />
      : <CampaignPerfBody brandId={brandId} campaignId={campaign.id} origin={campaign.origin} advanced={advanced}
          campaign={campaign} onCampaignChange={updateCampaign} onSync={() => void refreshPlatform()} syncing={syncing} syncError={syncError} />;
  } else {
    body = SLOTS[tab](slot);
  }

  return (
    <div className="flex max-w-[1260px] flex-col gap-4">
      {campaign?.simulation_mode && <p role="status" className="rounded-md bg-warning/10 p-3 text-sm">隔離模擬品牌：成效與學習只供演練，不代表真實投放。</p>}
      <WorkspaceHead brandId={brandId} campaign={campaign} workspace={workspace} tab={tab} onTab={changeTab} />
      {location.state?.parseWarning && <p className="text-sm text-warning">{location.state.parseWarning}</p>}
      {body}
    </div>
  );
}

/** Prototype `tabPerf()` for a draft: nothing is on a platform yet, so no results — the empty ruler shows where the
 * ads will land. */
function DraftPerf({ brandId, campaign: c, onGo, advanced }: {
  brandId: string; campaign: CampaignDetail; onGo: (target: StepTarget) => void; advanced: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-4">
      <section className="surface px-[22px] py-5" aria-label="成效">
        <ResultHero tone="neutral" title="還沒上架，沒有成效" note="上架並讀回核對後開始累積" />
        <div className="mt-3"><TargetRuler ads={[]} cap={capOf(c)} breakEven={c.cap.break_even} size="full" /></div>
      </section>
      {advanced}
      <ActionBar back={{ label: "總覽", to: `/brands/${brandId}/ads/campaigns/${c.id}` }}>
        <Button onClick={() => onGo("publish")}>確認上架清單 →</Button>
      </ActionBar>
    </div>
  );
}

export function CampaignWorkspace(props: Parameters<typeof Workspace>[0]) { return <Workspace key={`${props.brandId}:${props.campaignId}`} {...props} />; }
