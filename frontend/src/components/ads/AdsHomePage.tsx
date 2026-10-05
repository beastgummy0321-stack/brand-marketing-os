import { useCallback, useEffect, useState } from "react";
import { useApiRead } from "@/lib/useApiRead";
import { Link, useSearchParams } from "react-router-dom";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/layout/ui/button";
import { getHomeOverview, type HomeOverview } from "@/lib/adsHomeApi";
import { refreshQueue } from "@/lib/adsTriageApi";
import { getRecovery, type AdsRecovery } from "@/lib/adsStatusApi";
import { getOrgId } from "@/lib/auth";
import { formatInstant, useOrgClock } from "@/lib/orgClock";
import { ExistingCampaignDialog } from "./ExistingCampaignDialog";
import { BUDGET_EDIT_PARAM } from "./MonthlyBudgetPanel";
import { Chip, RecoverSteps } from "./patterns";
import { CampaignRows } from "./home/CampaignRows";
import { MonthMoney, monthNumber } from "./home/MonthMoney";
import { NextDates, type TodayNote } from "./home/NextDates";
import { QualityBand } from "./home/QualityBand";
import { TodayDecisions, homeBoard, type QueueState } from "./home/TodayDecisions";
import { proposalAction } from "./home/status";

type RecoveryState = { status: "loading" } | { status: "error" } | { status: "ready"; recovery: AdsRecovery };
type HomeState = { status: "loading" } | { status: "error" } | { status: "ready"; home: HomeOverview };

/** The query key an approval's month-budget link names itself by (F49-I11 builds `?budget=edit&return=<path>`). */
const BUDGET_RETURN_PARAM = "return";

/** `return` is taken only as a path inside this brand's ads centre (`/brands/{brandId}/ads/…`); anything else — another
 * brand, an absolute URL, `//host` — is dropped. */
export function budgetReturn(brandId: string, value: string | null): string | null {
  if (!value) return null;
  const prefix = `/brands/${brandId}/ads/`;
  return value.startsWith(prefix) && !value.includes("//") ? value : null;
}

/** F27-I17 recovery banner on a > 2 h worker gap: only while `recovering`; steps come from the backend as-is. */
function RecoveryBanner({ recovery }: { recovery: AdsRecovery }) {
  // `gap.start`／`gap.end` are ISO instants: HH:MM on the org clock (F50 Contract K).
  const { timezone } = useOrgClock();
  if (!recovery.recovering || !recovery.gap) return null;
  const hours = Math.floor(recovery.gap.minutes / 60);
  const minutes = recovery.gap.minutes % 60;
  return (
    <div className="rounded-xl border border-primary/20 bg-accent p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-base font-semibold">系統暫停了 {hours} 小時 {minutes} 分，正在補資料</p>
          <p className="mt-0.5 text-[13px] text-muted-foreground">
            {formatInstant(recovery.gap.start, timezone, "hm")} – {formatInstant(recovery.gap.end, timezone, "hm")} 沒有檢查・下面的數字補完後會更新
          </p>
        </div>
        <Chip tone="warn">這段時間平台可能照常花費</Chip>
      </div>
      <RecoverSteps steps={recovery.steps.map((s) => ({ label: s.label, state: s.state }))} />
    </div>
  );
}

/** 投放中心首頁 (F29-I11; prototype `docs/design/ads/prototype-v10-ads-center.html` `home()`): the month's title,
 * 接下來, the money card with the budget pace, the money-quality band, today's decisions (the period settle among
 * them) and the campaign rows. Two independent reads (Contract K, `useApiRead`): `GET …/home` (title, dates, money, pace, band, rows — each
 * block null on its own failure) and the brand queue (the 「今天」 count and the decision cards, both from this one
 * read); one failing never blanks the other (design-system §1.7 item 9), and a failed queue never reads as 「沒有要
 * 決定的事」. A home reload keeps the last good overview on screen until the new one lands. */
function AdsHome({ brandId }: { brandId: string }) {
  const clock = useOrgClock();
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
  const decisions = queueState.status === "ready" ? homeBoard(brandId, queueState.queue) : null;
  const note: TodayNote = syncing ? { kind: "syncing" }
    : queueState.status === "loading" ? { kind: "loading" }
    : queueState.status === "error" ? { kind: "error" }
    : decisions && decisions.open.length ? { kind: "open", count: decisions.count } : { kind: "none" };

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
  // F46-I09: 「設定／提高 N 月月預算」 links land here with `?budget=edit`; closing the area drops the param (replace),
  // so back／reload do not reopen it.
  const [searchParams, setSearchParams] = useSearchParams();
  const [openBudget] = useState(() => searchParams.get(BUDGET_EDIT_PARAM) === "edit");
  // F49 Contract Q (drill-11 Q4): an approval's month-budget gate links here with `return=<its path>`; only a path inside
  // this brand's ads centre is taken (never another site or brand). Read once: closing the area drops the params.
  const [returnTo] = useState(() => budgetReturn(brandId, openBudget ? searchParams.get(BUDGET_RETURN_PARAM) : null));
  const closeBudget = useCallback(() => {
    retryHome();
    setSearchParams((params) => { params.delete(BUDGET_EDIT_PARAM); params.delete(BUDGET_RETURN_PARAM); return params; }, { replace: true });
  }, [retryHome, setSearchParams]);
  const monthNo = monthNumber(home?.month, clock.today);
  const recovering = recoveryState.status === "ready" && recoveryState.recovery.recovering;

  // Zero campaigns and nothing spent this month: the prototype draws no first-run board, so the page shows one honest
  // empty card whose clear action is ＋ 建立活動 — no money card, band or decisions that could only print zeros.
  // A brand whose campaigns all closed this month is not a first run (drill-11 N3): the rows say so instead.
  const empty = home !== null && home.campaigns !== null && home.campaigns.length === 0 && home.spent === 0 && home.closed_this_month === 0;

  return (
    <div className="flex max-w-[1260px] flex-col gap-5">
      <PageHeader
        title={`${monthNo} 月的廣告`}
        description={home ? `第 ${home.day_of_month} 天／共 ${home.days_in_month} 天` : undefined}
        actions={empty ? undefined : (
          <>
            <Button asChild variant="outline"><Link to={`/brands/${brandId}/ads/month`}>每月回顧</Link></Button>
            {/* Not in the v10 prototype: the only home entry to bring an existing platform campaign in (kept). */}
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
        <MonthMoney brandId={brandId} state={homeState} onRetry={retryHome} scaleHref={scaleHref} onBudgetClosed={closeBudget} openBudget={openBudget} returnTo={returnTo} />
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
