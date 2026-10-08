import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { Skeleton } from "@/components/layout/Skeleton";
import type { CloseoutQueueRow, GradeMove, QueueCleanupAd, QueueItem, QueuePayload } from "@/lib/adsTriageApi";
import { Chip, Disclosure, GradeTermChip, ResultHero, Term, ThumbTiles, formatAmount, gradeWord, useAdsRules, type AdsRules } from "../patterns";
import { trendNote } from "../detail/GradeGroups";
import { cn } from "@/lib/utils";
import { formatInstant, useOrgClock } from "@/lib/orgClock";
import { currencyPrefix, wholeYuan } from "./MonthMoney";
import { CostBasis } from "./CostBasis";
import { perSaleAmount } from "../patterns/csv";
import { shortName } from "./NextDates";
import { CloseoutRow, DoneChip, QueueRow, closeoutAction, closeoutNote, decisionTitle, homeAction } from "./QueueRow";
import { SettleCard, SettleRow, settleRange } from "./SettleCard";
import { decisionBoard, decisionCount, settleAction, type HomeDecision } from "./status";
import type { HomeSync } from "@/lib/adsHomeApi";
import type { WorkerHealth } from "@/lib/useWorkerHealth";

/** v10 home 「需要你決定」 (prototype v10 `homeDecide()`): the brand queue's open decision rows — ad rows, the period
 * `settle` row and the ended campaigns' `closeout` rows — in their served `position` (F49 Contract Q: which rows are
 * decisions and their order are the backend's); three as cards (the settle card spans the row), the rest behind one
 * fold; decisions already handled behind 「今天處理過」. The count is the served `decisions.open`. The queue is its
 * own request: loading, syncing and failure only change this block. */

export type QueueState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; queue: QueuePayload };

const SHOWN = 3;

export type { HomeDecision };

/** The home board (`status.ts::decisionBoard`) and its count (`decisionCount`), shared with the flow pages' 「第 N 件／共
 * M 件」 and the settle page. */
export function homeBoard(brandId: string, queue: QueuePayload): { open: HomeDecision[]; done: HomeDecision[]; count: number } {
  const board = decisionBoard(brandId, queue);
  return { ...board, count: decisionCount(queue, board) };
}

const keyOf = (d: HomeDecision) => (d.kind === "item" ? d.item.id : `${d.kind}-${d.row.id}`);

/** 「09/22 22:40」 on the org clock (prototype `SYNC_AT`; F50 Contract K). */
export function stamp(iso: string, timezone: string): string {
  return formatInstant(iso, timezone, "md_hm");
}

/** 「從划算變偏貴」 from the backend's own `grade_move` in the served words (F48 Contract R-API); no move (or the rules
 * not loaded yet) → the prototype's plain 「每筆變多了」 (never a move guessed from the trend or from `previous_grade`). */
function moveText(move: GradeMove | null, rules: AdsRules | null): string {
  return move && rules ? `從${gradeWord(rules, move.from)}變${gradeWord(rules, move.to)}` : "每筆變多了";
}

type Props = {
  brandId: string;
  state: QueueState;
  /** A platform read is running: the prototype holds the judgement until it finishes. */
  syncing: boolean;
  /** F27-I17: right after a worker gap every action is replaced by one honest placeholder. */
  recovering: boolean;
  sync: Pick<HomeSync, "last_success_at" | "next_at"> & Partial<HomeSync> | null;
  worker?: Pick<WorkerHealth, "state" | "recheck">;
  fresh?: boolean;
  onRetry: () => void;
};

export function TodayDecisions({ brandId, state, syncing, recovering, sync, worker, fresh = true, onRetry }: Props) {
  const { timezone } = useOrgClock();
  const board = state.status === "ready" ? homeBoard(brandId, state.queue) : null;
  const open = board?.open ?? [];
  const done = board?.done ?? [];
  const workerState = worker?.state ?? sync?.worker_health?.state ?? "unknown";
  const waiting = syncing && workerState === "alive";
  const primaryKey = open.find((d) => d.kind === "settle" ? settleAction(brandId, d.row).href
    : d.kind === "closeout" ? closeoutAction(d.row).href : homeAction(brandId, d.item).href);
  const chip = waiting
    ? <Chip tone="accent">同步中・完成後才判斷</Chip>
    : board && open.length ? <Chip>{board.count} 件</Chip> : null;

  let body;
  if (waiting || state.status === "loading") {
    body = (
      <div className="grid grid-cols-1 gap-3.5 min-[1100px]:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]" aria-busy="true">
        {[0, 1].map((k) => (
          <div key={k} className="flex flex-col gap-3.5 rounded-xl border border-border bg-card px-5 py-[18px]">
            <Skeleton className="h-3.5 w-[30%]" /><Skeleton className="h-3.5 w-[80%]" /><Skeleton className="h-3.5 w-[60%]" /><Skeleton className="h-10 rounded-lg" />
          </div>
        ))}
      </div>
    );
  } else if (state.status === "error") {
    body = (
      <div className="grid items-center rounded-xl bg-danger/10 sm:grid-cols-[minmax(0,1fr)_auto] [&>[data-slot=result-hero]]:bg-transparent">
        <ResultHero
          tone="bad"
          title="今天的判斷讀取失敗"
          note={<><span className="block break-words">{state.message}</span><span className="block">{`${sync?.last_success_at ? `上次成功 ${stamp(sync.last_success_at, timezone)}・` : ""}已保存的決定都還在`}</span></>}
        />
        <Button variant="outline" className="mx-5 mb-5 justify-self-start sm:mb-0" onClick={onRetry}>重新讀取</Button>
      </div>
    );
  } else if (!open.length) {
    const note = [
      sync?.last_success_at ? `最近成功讀取 ${stamp(sync.last_success_at, timezone)}` : null,
      workerState === "alive" && fresh && sync?.next_at ? `下次同步預估 ${formatInstant(sync.next_at, timezone, "hm")}` : null,
    ].filter(Boolean).join("・");
    body = (
      <>
        <div className="flex items-center gap-4 rounded-xl border border-border bg-card px-6 py-7">
          <div className="grid size-[52px] shrink-0 place-items-center rounded-full bg-muted text-2xl text-muted-foreground" aria-hidden="true">—</div>
          <div className="min-w-0 flex-1">
            <b className="text-lg">目前沒有待決定的項目</b>
            {note && <div className="mt-0.5 text-sm text-muted-foreground">{note}</div>}
          </div>
          <Button asChild variant="outline"><Link to={`/brands/${brandId}/ads/month`}>看每月回顧</Link></Button>
        </div>
        <HandledFold brandId={brandId} done={done} recovering={recovering} />
      </>
    );
  } else {
    const shown = open.slice(0, SHOWN);
    const rest = open.slice(SHOWN);
    body = (
      <>
        <div className="grid grid-cols-1 gap-3.5 min-[1100px]:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
          {shown.map((d) => (d.kind === "settle"
            ? <SettleCard key={keyOf(d)} brandId={brandId} row={d.row} recovering={recovering} primary={d === primaryKey} />
            : d.kind === "closeout"
            ? <CloseoutCard key={keyOf(d)} row={d.row} recovering={recovering} primary={d === primaryKey} />
            : <DecisionCardFor key={keyOf(d)} brandId={brandId} item={d.item} recovering={recovering} primary={d === primaryKey} />))}
        </div>
        {rest.length > 0 && (
          <Disclosure label={`還有 ${rest.length} 件要決定`}>
            {rest.map((d) => (d.kind === "settle"
              ? <SettleRow key={keyOf(d)} brandId={brandId} row={d.row} recovering={recovering} />
              : d.kind === "closeout"
              ? <CloseoutRow key={keyOf(d)} row={d.row} recovering={recovering} />
              : <QueueRow key={keyOf(d)} brandId={brandId} item={d.item} recovering={recovering} />))}
          </Disclosure>
        )}
        <HandledFold brandId={brandId} done={done} recovering={recovering} />
      </>
    );
  }

  return (
    <section className="flex flex-col gap-2.5" aria-labelledby="decide">
      <h2 id="decide" tabIndex={-1} className="flex scroll-mt-[72px] items-center gap-2 text-base font-semibold outline-none">需要你決定{chip}</h2>
      {workerState !== "alive" && <div className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
        <Chip tone={workerState === "stopped" ? "warn" : "neutral"}>{workerState === "stopped" ? "背景執行已停止" : "背景狀態未確認"}</Chip>
        {sync?.eligible_at && <span>同步到期時間 {formatInstant(sync.eligible_at, timezone, "md_hm")}・執行時間尚無法確認</span>}
        {worker && <Button variant="link" size="sm" onClick={() => void worker.recheck()}>重新確認背景狀態</Button>}
      </div>}
      {body}
    </section>
  );
}

/** Prototype `doneLabel(q)`: what was decided, in one line. */
function doneLabel(d: HomeDecision, rules: AdsRules | null): string {
  if (d.kind === "settle") return `結算上一期 ${settleRange(d.row)}`;
  if (d.kind === "closeout") return d.row.message;
  const item = d.item;
  if (item.kind_key === "cleanup") return `清理：${decisionTitle(item)}`;
  if (item.kind_key === "worse") return `${triggerText(item, rules)}：${item.triage.name ?? "未命名廣告"}`;
  return decisionTitle(item);
}

function HandledFold({ brandId, done, recovering }: { brandId: string; done: HomeDecision[]; recovering: boolean }) {
  const rules = useAdsRules();
  const { timezone } = useOrgClock();
  if (!done.length) return null;
  return (
    <Disclosure label={`今天處理過 ${done.length} 件`}>
      {done.map((d) => {
        const action = d.kind === "settle" ? settleAction(brandId, d.row)
          : d.kind === "closeout" ? closeoutAction(d.row) : homeAction(brandId, d.item, timezone);
        // drill-10 Q2: the chip opens the decision (a deferred one shows 「M/D 再看」 and leads back to its change set).
        return (
          <div key={keyOf(d)} className="flex flex-wrap items-center gap-3 border-t border-border py-2 first:border-t-0">
            <span className="min-w-0 flex-1 text-sm [overflow-wrap:anywhere]">{doneLabel(d, rules)}
              {d.kind === "item" && d.item.proposal?.reason && <span className="block text-xs text-muted-foreground">{d.item.proposal.reason}</span>}
            </span>
            {recovering ? <Chip>補完資料後更新</Chip> : <DoneChip action={action} />}
          </div>
        );
      })}
    </Disclosure>
  );
}

const CARD = "flex flex-col gap-3.5 rounded-xl border bg-card px-5 py-[18px]";

function CardHead({ label, className, campaign }: { label: string; className: string; campaign: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <Chip className={className}>{label}</Chip>
      <span className="min-w-0 text-right text-sm text-muted-foreground [overflow-wrap:anywhere]">{campaign}</span>
    </div>
  );
}

/** The card's one step; with no proposal yet `homeAction` already uses the prototype's first-step words. */
function CardAction({ brandId, item, primary }: { brandId: string; item: QueueItem; primary: boolean }) {
  const action = homeAction(brandId, item);
  if (!action.href) return null;
  return (
    <Button asChild variant={primary ? "default" : "outline"} className="h-10 w-full">
      <Link to={action.href}>{action.label} →</Link>
    </Button>
  );
}

function Recovering() {
  return <Chip className="self-start">補完資料後更新</Chip>;
}

function Thumb({ url, size }: { url: string | null; size: number }) {
  const style = { width: size, height: size };
  return url
    ? <img src={url} alt="" className="shrink-0 rounded-lg object-cover" style={style} />
    : <span className="shrink-0 rounded-lg bg-muted" style={style} aria-hidden="true" />;
}

function DecisionCardFor(props: { brandId: string; item: QueueItem; recovering: boolean; primary: boolean }) {
  if (props.item.kind_key === "cleanup") return <CleanupCard {...props} />;
  if (props.item.kind_key === "worse") return <WorseCard {...props} />;
  return <RefreshCard {...props} />;
}

function CleanupFigure({ ad, breakEven }: { ad: QueueCleanupAd; breakEven: number | null }) {
  if (ad.grade === "wasted") return <>花 {currencyPrefix(ad.currency ?? null)}{formatAmount(ad.spend) ?? "—"}・0 筆</>;
  if (ad.cost_per_result === null) return <>每筆 —</>;
  return (
    <>
      每筆 {currencyPrefix(ad.currency ?? null)}{wholeYuan(ad.cost_per_result)}{!ad.currency && "（幣別未確認）"}
      <CostBasis value={breakEven} currency={ad.currency ?? null} />
    </>
  );
}

/** Prototype `cleanCard()`: the proposed cut, 沒賣出 first, with the daily saving when the last 7 days are known. */
function CleanupCard({ brandId, item, recovering, primary }: { brandId: string; item: QueueItem; recovering: boolean; primary: boolean }) {
  const cleanup = item.cleanup;
  const ads = cleanup?.ads ?? [];
  const red = ads.length > 0 && ads.every((a) => a.grade === "over" || a.grade === "wasted");
  const saving = cleanup?.daily_saving ?? null;
  const breakEven = item.triage.target.break_even ?? null;
  const title = ads.length
    ? `${red ? "關掉色帶裡紅色的" : "關掉"} ${ads.length} 則${saving === null ? "" : `，每天省約 ${formatAmount(saving)}（幣別未確認）`}`
    : "預算放不下全部在投的廣告";
  return (
    <article className={cn(CARD, "border-danger/30")} aria-label={decisionTitle(item)}>
      <CardHead label="花錢沒效" className="bg-zone-over text-grade-wasted-foreground" campaign={cleanup?.campaign_name ?? item.triage.campaign_name} />
      <div className="text-base font-semibold">{title}</div>
      {ads.length > 0 && (
        <div className="flex flex-col gap-2">
          {ads.map((ad) => (
            <div key={ad.entity_id} className="grid grid-cols-[32px_minmax(0,1fr)_auto_auto] items-center gap-2.5">
              <Thumb url={ad.thumbnail_url} size={32} />
              <span className="min-w-0 text-sm [overflow-wrap:anywhere]">{ad.name ?? "未命名廣告"}</span>
              <GradeTermChip grade={ad.grade} />
              <span className="numeric min-w-[92px] text-right text-sm whitespace-nowrap text-muted-foreground">
                <CleanupFigure ad={ad} breakEven={ad.currency && item.triage.target.break_even_unit?.currency === ad.currency ? breakEven : null} />
              </span>
            </div>
          ))}
        </div>
      )}
      {recovering ? <Recovering /> : <CardAction brandId={brandId} item={item} primary={primary} />}
    </article>
  );
}

/** Prototype `worseCard()`: 變貴 is the grade moving against this campaign's cap (`grade_move`); the week-over-week
 * trend is only the footnote. */
function WorseCard({ brandId, item, recovering, primary }: { brandId: string; item: QueueItem; recovering: boolean; primary: boolean }) {
  const t = item.triage;
  const rules = useAdsRules();
  const prev = t.previous.cost_per_result;
  const cur = t.current.cost_per_result;
  const cap = t.target.value;
  const comparable = t.cap_comparison?.reason === null && t.target.cap_unit?.currency === t.current.currency && !!t.current.currency;
  const who = shortName(t.campaign_name);
  const capWord = t.target.basis === "break_even"
    ? <>{who}暫用<Term k="break_even" value={t.target.break_even}>打平線</Term></>
    : <>{who}的<Term k="cap">上限</Term></>;
  const over = cap !== null && cur !== null && cur > cap;
  return (
    <article className={cn(CARD, "border-border")} aria-label={t.name ?? "未命名廣告"}>
      <CardHead label={triggerText(item, rules)} className="bg-zone-watch text-warning-strong" campaign={t.campaign_name} />
      <div className="text-base font-semibold [overflow-wrap:anywhere]">{t.name ?? "未命名廣告"}</div>
      <div>
        <div className="numeric text-base font-semibold [overflow-wrap:anywhere]">
          每筆 {currencyPrefix(t.current.currency ?? null)}{prev !== null && t.current.currency && t.previous.currency === t.current.currency && `${perSaleAmount(prev)} → `}{perSaleAmount(cur) ?? "—"}
          {cur !== null && !t.current.currency && "（幣別未確認）"}
          {comparable && cap !== null && cur !== null && <>，{over ? "超過" : "還在"}{capWord} {formatAmount(cap)}{over ? "" : " 內"}</>}
        </div>
        <CostBasis value={t.target.break_even_unit?.currency === t.current.currency ? t.target.break_even ?? null : null} currency={t.current.currency ?? null} />
        <div className="mt-1 text-xs text-muted-foreground">{trendNote(t)}（只當參考）</div>
      </div>
      <div className="flex-1" />
      {recovering ? <Recovering /> : <CardAction brandId={brandId} item={item} primary={primary} />}
    </article>
  );
}

function triggerText(item: QueueItem, rules: AdsRules | null): string {
  if (item.trigger_reason === "persistently_over_cap") return "成本持續超過上限";
  if (item.trigger_reason === "currently_over_cap") return "成本超過上限";
  return moveText(item.triage.grade_move, rules);
}

/** F49 Contract Q: an ended campaign's closeout decision, in the same card shape as the others — the served sentence
 * (「「X」已結束，待結案」), the end date and any ads still running on the platform, and 結案這一期 to the row's own link. */
function CloseoutCard({ row, recovering, primary }: { row: CloseoutQueueRow; recovering: boolean; primary: boolean }) {
  const action = closeoutAction(row);
  const note = closeoutNote(row);
  return (
    <article className={cn(CARD, "border-border")} aria-label={row.message}>
      <CardHead label="結案" className="bg-zone-watch text-warning-strong" campaign={row.closeout.campaign_name} />
      <div className="text-base font-semibold [overflow-wrap:anywhere]">{row.message}</div>
      {note && <div className="text-sm text-muted-foreground">{note}</div>}
      <div className="flex-1" />
      {recovering ? <Recovering /> : action.href && (
        <Button asChild variant={primary ? "default" : "outline"} className="h-10 w-full"><Link to={action.href}>{action.label} →</Link></Button>
      )}
    </article>
  );
}

/** Not drawn by the prototype's home: the same card shape for a `refresh_creative` row (too few readable ads). */
function RefreshCard({ brandId, item, recovering, primary }: { brandId: string; item: QueueItem; recovering: boolean; primary: boolean }) {
  const refresh = item.refresh;
  const thumbs = refresh?.thumbnails.slice(0, 4) ?? [];
  return (
    <article className={cn(CARD, "border-border")} aria-label={decisionTitle(item)}>
      <CardHead label="素材不夠判讀" className="" campaign={refresh?.campaign_name ?? item.triage.campaign_name} />
      <div className="text-base font-semibold">{decisionTitle(item)}</div>
      <ThumbTiles items={thumbs} size={32} hollow={4 - thumbs.length} />
      <div className="flex-1" />
      {recovering ? <Recovering /> : <CardAction brandId={brandId} item={item} primary={primary} />}
    </article>
  );
}
