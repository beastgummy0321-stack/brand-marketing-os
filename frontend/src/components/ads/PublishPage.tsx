import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { Skeleton } from "@/components/layout/Skeleton";
import { Button } from "@/components/layout/ui/button";
import { getCampaign, type CampaignDetail } from "@/lib/adsApi";
import { getHandoff, type HandoffWorkspace } from "@/lib/adsHandoffApi";
import { fetchChannels, fetchLaunchView, type LaunchView } from "@/lib/adsLaunchApi";
import { useApiRead } from "@/lib/useApiRead";
import { LaunchStalePanel, type LaunchOutcome } from "./LaunchStalePanel";
import { ReadFailed } from "./patterns";
import { PublishList } from "./publish/PublishList";
import { PublishPlatform } from "./publish/PublishPlatform";
import { PublishVerify } from "./publish/PublishVerify";
import { allowsStep, campaignPath, launchPlatform, publishPath, urlOfStep } from "./publish/PublishFlow";

/** F30-I13 publish page (prototype v10 `pubPage()`): 確認上架清單 → 到平台完成 → 讀回核對 at
 * `…/campaigns/:c/publish/{list,platform,verify}`. `GET …/launch` reports the step; a URL the step does not allow yet
 * (or no step) redirects to it, and a stale launch is decided on the platform step with F28's `LaunchStalePanel`.
 * The campaign, the launch view and the channel list are separate reads that fail on their own. Nothing on this page
 * writes to a platform. */
export function PublishPage({ brandId, campaignId, step }: { brandId: string; campaignId: string; step?: string }) {
  const navigate = useNavigate();
  const campaignRead = useApiRead(() => getCampaign(brandId, campaignId), [brandId, campaignId]);
  const channels = useApiRead(() => fetchChannels(brandId), [brandId]);
  const launchRead = useApiRead(() => fetchLaunchView(brandId, campaignId), [brandId, campaignId]);
  // A write answers with the refreshed view; it stands in until the next read.
  const [view, setView] = useState<LaunchView | null>(null);
  useEffect(() => { if (launchRead.status === "ready") setView(launchRead.data); }, [launchRead.status, launchRead.data]);
  const [campaign, setCampaign] = useState<CampaignDetail | null>(null);
  useEffect(() => { if (campaignRead.status === "ready") setCampaign(campaignRead.data); }, [campaignRead.status, campaignRead.data]);
  const [moving, setMoving] = useState(false);
  const [staleOutcome, setStaleOutcome] = useState<LaunchOutcome | null>(null);
  const [moveError, setMoveError] = useState<string | null>(null);

  const home = `/brands/${encodeURIComponent(brandId)}/ads`;
  const name = campaign?.name ?? view?.items.find((i) => i.kind === "campaign")?.name ?? "活動";
  const crumb = [{ label: "投放中心", href: home }, { label: name, href: campaignPath(brandId, campaignId) }, { label: "首次上架" }];
  const platform = launchPlatform(campaign, channels.data);

  // Approval and the batch readback move the page on only once the server answered with the new step.
  const moveTo = useCallback(async (read: () => Promise<LaunchView>, target: "platform" | "verify") => {
    setMoving(true); setMoveError(null);
    try { setView(await read()); navigate(publishPath(brandId, campaignId, target)); }
    catch (err) { setMoveError(err instanceof Error ? err.message : "讀取上架清單失敗。"); }
    finally { setMoving(false); }
  }, [brandId, campaignId, navigate]);

  const wrap = (body: ReactNode) => (
    <div className="flex max-w-[1260px] flex-col gap-4">
      <Breadcrumb items={crumb} />
      {body}
    </div>
  );

  if (campaign && (campaign.origin === "imported" || campaign.capabilities?.unavailable.publish)) {
    return wrap(
      <div className="surface flex flex-wrap items-center gap-4 px-[22px] py-5">
        <p className="min-w-0 flex-1 text-sm">{campaign.capabilities?.unavailable.publish ?? "此活動只支援素材手動交接，不支援內部發布。"}</p>
        <Button asChild><Link to={`${campaignPath(brandId, campaignId)}?tab=assets`}>前往自帶素材安排</Link></Button>
      </div>,
    );
  }
  if (launchRead.status === "error" && !view) {
    return wrap(<ReadFailed what={`上架清單讀不到：${launchRead.error}。平台上沒有任何改動。`} onRetry={launchRead.reload} />);
  }
  if (!view) return wrap(<><Skeleton className="h-16 w-96" /><Skeleton className="h-60 w-full" /></>);
  if (!allowsStep(view.step, step)) return <Navigate replace to={publishPath(brandId, campaignId, urlOfStep(view.step))} />;

  const moveNote = (moving || moveError) && (
    moveError
      ? <ReadFailed what={`已記錄，但上架清單沒有讀到：${moveError}`} onRetry={launchRead.reload} />
      : <p role="status" className="text-sm text-muted-foreground">讀取上架清單…</p>
  );
  const campaignFailed = campaignRead.status === "error" ? campaignRead.error : null;

  if (step === "list") {
    return wrap(<>
      {moveNote}
      <PublishList brandId={brandId} campaignId={campaignId} name={name} campaign={campaign} campaignFailed={campaignFailed}
        onCampaignRetry={campaignRead.reload} onCampaignSaved={(c) => { setCampaign(c); launchRead.reload(); }}
        view={view} onApproved={() => void moveTo(() => fetchLaunchView(brandId, campaignId), "platform")} />
    </>);
  }
  if (step === "platform" && view.step === "stale") {
    return wrap(<StaleStep brandId={brandId} campaignId={campaignId} outcome={staleOutcome} onOutcome={setStaleOutcome} onDecided={launchRead.reload} />);
  }
  const outcomeNote = staleOutcome && <OutcomeNote outcome={staleOutcome} />;
  if (step === "platform") {
    return wrap(<>
      {moveNote}{outcomeNote}
      <PublishPlatform brandId={brandId} campaignId={campaignId} name={name} view={view} platform={platform} onView={setView}
        onReadBack={(next) => { setView(next); navigate(publishPath(brandId, campaignId, "verify")); }} />
    </>);
  }
  return wrap(<PublishVerify brandId={brandId} campaignId={campaignId} name={name} view={view} platform={platform} onView={setView} />);
}

function OutcomeNote({ outcome }: { outcome: LaunchOutcome }) {
  return <p role={outcome.tone === "error" ? "alert" : "status"} className={outcome.tone === "error" ? "rounded-lg bg-danger/10 p-3 text-sm text-danger" : "rounded-lg bg-success/10 p-3 text-sm text-success"}>{outcome.text}</p>;
}

/** The stale step: F28's panel works on the handoff workspace (the approved set's items and the approved → now diff).
 * A decision re-reads the launch view, which then reports the platform step again. */
function StaleStep({ brandId, campaignId, outcome, onOutcome, onDecided }: {
  brandId: string; campaignId: string; outcome: LaunchOutcome | null;
  onOutcome: (outcome: LaunchOutcome | null) => void; onDecided: () => void;
}) {
  const [seq, setSeq] = useState(0);
  const handoff = useApiRead((signal) => getHandoff(brandId, campaignId, signal), [brandId, campaignId, seq]);
  const [data, setData] = useState<HandoffWorkspace | null>(null);
  useEffect(() => { if (handoff.status === "ready") setData(handoff.data); }, [handoff.status, handoff.data]);
  const decided = useRef(onDecided);
  decided.current = onDecided;
  // The launch view said stale but the handoff no longer does: read the launch again for the current step.
  const settled = data !== null && data.launch_stale === null;
  useEffect(() => { if (settled) decided.current(); }, [settled]);

  if (handoff.status === "error" && !data) return <ReadFailed what={`上架清單讀不到：${handoff.error}。`} onRetry={handoff.reload} />;
  if (!data || !data.launch_stale) return <Skeleton className="h-60 w-full" />;
  return (
    <>
      {outcome && <OutcomeNote outcome={outcome} />}
      <LaunchStalePanel brandId={brandId} campaignId={campaignId} stale={data.launch_stale} items={data.items}
        onDecided={(value, result) => { setData(value); onOutcome(result); }}
        onReload={(result) => { onOutcome(result ?? null); setSeq((n) => n + 1); decided.current(); }} />
    </>
  );
}
