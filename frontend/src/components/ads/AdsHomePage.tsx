import { useCallback, useEffect, useState } from "react";
import { useApiRead } from "@/lib/useApiRead";
import { Link } from "react-router-dom";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/layout/ui/button";
import { getHomeOverview, type HomeOverview } from "@/lib/adsHomeApi";
import { refreshQueue } from "@/lib/adsTriageApi";
import { getRecovery, type AdsRecovery } from "@/lib/adsStatusApi";
import { getOrgId } from "@/lib/auth";
import { ExistingCampaignDialog } from "./ExistingCampaignDialog";
import { Chip, RecoverSteps } from "./patterns";
import { CampaignRows } from "./home/CampaignRows";
import { MonthMoney, monthNumber } from "./home/MonthMoney";
import { NextDates, type TodayNote } from "./home/NextDates";
import { QualityBand } from "./home/QualityBand";
import { TodayDecisions, homeDecisions, type QueueState } from "./home/TodayDecisions";
import { proposalAction } from "./home/status";

export { STATUS_LABEL, STATUS_TONE } from "./home/status";

type RecoveryState = { status: "loading" } | { status: "error" } | { status: "ready"; recovery: AdsRecovery };
type HomeState = { status: "loading" } | { status: "error" } | { status: "ready"; home: HomeOverview };

/** 瀏覽器本地時區的 HH:MM——`gap.start`／`gap.end` 一律是帶時區的 ISO instant。 */
function formatHM(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/** F27-I17 recovery banner on a > 2 h worker gap: only while `recovering`; steps come from the backend as-is. */
function RecoveryBanner({ recovery }: { recovery: AdsRecovery }) {
  if (!recovery.recovering || !recovery.gap) return null;
  const hours = Math.floor(recovery.gap.minutes / 60);
  const minutes = recovery.gap.minutes % 60;
  return (
    <div className="rounded-xl border border-primary/20 bg-accent p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-base font-semibold">系統暫停了 {hours} 小時 {minutes} 分，正在補資料</p>
          <p className="mt-0.5 text-[13px] text-muted-foreground">
            {formatHM(recovery.gap.start)} – {formatHM(recovery.gap.end)} 沒有檢查・下面的數字補完後會更新
          </p>
        </div>
        <Chip tone="warn">這段時間平台可能照常花費</Chip>
      </div>
      <RecoverSteps steps={recovery.steps.map((s) => ({ label: s.label, state: s.state }))} />
    </div>
  );
}

/** 投放中心首頁 = board D (F28-I08; prototype `docs/design/ads/prototype-v9-ads-center.html` `home()`): the month's
 * title, 接下來, the money card with the budget pace, the money-quality band, today's decisions and the campaign
 * rows. Two independent reads (Contract K, `useApiRead`): `GET …/home` (title, dates, money, pace, band, rows — each
 * block null on its own failure) and the brand queue (the 「今天」 count and the decision cards, both from this one
 * read); one failing never blanks the other (design-system §1.7 item 9), and a failed queue never reads as 「沒有要
 * 決定的事」. A home reload keeps the last good overview on screen until the new one lands. */
function AdsHome({ brandId }: { brandId: string }) {
  const homeRead = useApiRead((signal) => getHomeOverview(brandId, undefined, signal), [brandId]);
  const homeState: HomeState = homeRead.data !== null ? { status: "ready", home: homeRead.data }
    : homeRead.status === "error" ? { status: "error" } : { status: "loading" };
  const queueRead = useApiRead((signal) => refreshQueue(brandId, signal), [brandId]);
  const queueState: QueueState = queueRead.status === "ready" ? { status: "ready", queue: queueRead.data }
    : queueRead.status === "error" ? { status: "error", message: queueRead.error } : { status: "loading" };
  const [recoveryState, setRecoveryState] = useState<RecoveryState>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    getRecovery(brandId, controller.signal)
      .then((recovery) => { if (!controller.signal.aborted) setRecoveryState({ status: "ready", recovery }); })
      .catch(() => { if (!controller.signal.aborted) setRecoveryState({ status: "error" }); });
    return () => controller.abort();
  }, [brandId]);

  const home = homeState.status === "ready" ? homeState.home : null;
  const syncing = (home?.campaigns ?? []).some((c) => c.draft === null && c.sync_state === "syncing");
  const decisions = queueState.status === "ready" ? homeDecisions(brandId, queueState.queue) : null;
  const note: TodayNote = syncing ? { kind: "syncing" }
    : queueState.status === "loading" ? { kind: "loading" }
    : queueState.status === "error" ? { kind: "error" }
    : decisions && decisions.open.length ? { kind: "open", count: decisions.open.length } : { kind: "none" };

  // 「看加預算建議」: the first open `scale_budget` row's own step (budget owner id, `home/status.ts` "budget" branch).
  const scaleHref = (() => {
    if (queueState.status !== "ready") return null;
    for (const item of queueState.queue.items) {
      if (item.kind_key !== "scale_budget" || !item.scale) continue;
      const action = proposalAction(brandId, item.triage.campaign_id, item.scale.owner.id, item.proposal, "budget");
      if (!action.done) return action.href;
    }
    return null;
  })();

  const jump = useCallback(() => {
    const target = document.getElementById("decide");
    target?.scrollIntoView({ behavior: "smooth", block: "start" });
    target?.focus({ preventScroll: true });
  }, []);
  const retryHome = homeRead.reload;
  const monthNo = monthNumber(home?.month);
  const recovering = recoveryState.status === "ready" && recoveryState.recovery.recovering;

  // Zero campaigns and nothing spent this month: the prototype draws no first-run board, so the page shows one honest
  // empty card whose clear action is ＋ 建立活動 — no money card, band or decisions that could only print zeros.
  const empty = home !== null && home.campaigns !== null && home.campaigns.length === 0 && !home.spent;

  return (
    <div className="flex max-w-[1260px] flex-col gap-5">
      <PageHeader
        title={`${monthNo} 月的廣告`}
        description={home ? `第 ${home.day_of_month} 天／共 ${home.days_in_month} 天` : undefined}
        actions={empty ? undefined : (
          <>
            <Button asChild variant="outline"><Link to={`/brands/${brandId}/ads/month`}>每月回顧</Link></Button>
            {/* Not in the v9 prototype: the only home entry to bring an existing platform campaign in (kept). */}
            <ExistingCampaignDialog brandId={brandId} />
            <Button asChild variant="outline">
              <Link to={`/brands/${brandId}/ads/new`}><span aria-hidden="true">＋</span> 建立活動</Link>
            </Button>
          </>
        )}
      />
      {recoveryState.status === "ready" && <RecoveryBanner recovery={recoveryState.recovery} />}
      {empty ? <EmptyBoard brandId={brandId} /> : <>
        <NextDates home={home} note={note} onJump={jump} />
        <MonthMoney brandId={brandId} state={homeState} onRetry={retryHome} scaleHref={scaleHref} onBudgetClosed={retryHome} />
        <QualityBand state={homeState} onRetry={retryHome} />
        <TodayDecisions
          brandId={brandId}
          state={queueState}
          syncing={syncing}
          recovering={recovering}
          sync={home?.sync ?? null}
          onRetry={queueRead.reload}
        />
        <CampaignRows brandId={brandId} state={homeState} onRetry={retryHome} />
      </>}
    </div>
  );
}

/** First run: no campaign yet. One primary action; bringing an existing platform campaign in stays secondary. */
function EmptyBoard({ brandId }: { brandId: string }) {
  return (
    <section aria-labelledby="ads-empty" className="surface flex flex-wrap items-center gap-5 px-7 py-8">
      <div className="min-w-0 flex-1">
        <h2 id="ads-empty" className="text-lg font-semibold">還沒有進行中的活動</h2>
        <p className="mt-1 text-sm text-muted-foreground">建立第一個活動後，這裡會開始算這個月花了多少、划不划算</p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <ExistingCampaignDialog brandId={brandId} />
        <Button asChild>
          <Link to={`/brands/${brandId}/ads/new`}><span aria-hidden="true">＋</span> 建立活動</Link>
        </Button>
      </div>
    </section>
  );
}

export function AdsHomePage(props: { brandId: string }) {
  return <AdsHome key={`${getOrgId()}:${props.brandId}`} {...props} />;
}
