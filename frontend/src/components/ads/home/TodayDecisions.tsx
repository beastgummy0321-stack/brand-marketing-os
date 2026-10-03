import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { Skeleton } from "@/components/layout/Skeleton";
import type { GradeMove, QueueCleanupAd, QueueItem, QueuePayload } from "@/lib/adsTriageApi";
import { Chip, Disclosure, GradeTermChip, MoneyTag, ResultHero, Term, ThumbTiles, formatAmount, gradeWord, useAdsRules, type AdsRules } from "../patterns";
import { trendNote } from "../detail/GradeGroups";
import { cn } from "@/lib/utils";
import { wholeYuan } from "./MonthMoney";
import { perSaleAmount } from "../patterns/csv";
import { shortName } from "./NextDates";
import { DoneChip, QueueRow, decisionTitle, homeAction } from "./QueueRow";
import { SettleCard, SettleRow, settleRange } from "./SettleCard";
import { decisionBoard, decisionRows, settleAction, type HomeDecision } from "./status";

/** v10 home 「需要你決定」 (prototype v10 `homeDecide()`): the brand queue's open `cleanup`, `worse`, period `settle`
 * and `refresh_creative` rows, in that order; three as cards (the settle card spans the row), the rest behind one
 * fold; decisions already handled behind 「今天處理過」. The queue is its own request: loading, syncing and failure
 * only change this block. */

export type QueueState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; queue: QueuePayload };

const SHOWN = 3;

/** The ad-level home decisions of a queue, split into open and handled, in board order (the settle row is not an ad
 * row; `homeBoard` adds it). Also read by the settle page for its 「第 N 件」 position. F47-I07: the rule lives in
 * `status.ts::decisionRows`, shared with the flow pages' 「第 N 件／共 M 件」. */
export function homeDecisions(_brandId: string, queue: QueuePayload): { open: QueueItem[]; done: QueueItem[] } {
  return decisionRows(queue);
}

export type { HomeDecision };

/** Board order (prototype): cleanup, worse, settle, refresh_creative. The count on 「今天」 is `open.length`. */
export const homeBoard = decisionBoard;

const keyOf = (d: HomeDecision) => (d.kind === "settle" ? `settle-${d.row.id}` : d.item.id);

/** 「09/22 22:40」 in the browser's time zone (prototype `SYNC_AT`). */
export function stamp(iso: string): string {
  const d = new Date(iso);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}/${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function hm(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
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
  sync: { last_success_at: string | null; next_at: string | null } | null;
  onRetry: () => void;
};

export function TodayDecisions({ brandId, state, syncing, recovering, sync, onRetry }: Props) {
  const board = state.status === "ready" ? homeBoard(brandId, state.queue) : null;
  const open = board?.open ?? [];
  const done = board?.done ?? [];
  const chip = syncing
    ? <Chip tone="accent">同步中・完成後才判斷</Chip>
    : state.status === "ready" && open.length ? <Chip>{open.length} 件</Chip> : null;

  let body;
  if (syncing || state.status === "loading") {
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
      <div className="relative">
        <ResultHero
          tone="bad"
          title="今天的判斷讀取失敗"
          note={`${sync?.last_success_at ? `上次成功 ${stamp(sync.last_success_at)}・` : ""}已保存的決定都還在`}
        />
        <Button variant="outline" className="absolute top-1/2 right-5 -translate-y-1/2" onClick={onRetry}>重新讀取</Button>
      </div>
    );
  } else if (!open.length) {
    const note = [
      sync?.last_success_at ? `${stamp(sync.last_success_at)} 同步後判讀完成` : null,
      sync?.next_at ? `下次同步 ${hm(sync.next_at)}` : null,
    ].filter(Boolean).join("・");
    body = (
      <>
        <div className="flex items-center gap-4 rounded-xl border border-border bg-card px-6 py-7">
          <div className="grid size-[52px] shrink-0 place-items-center rounded-full bg-success text-2xl text-white" aria-hidden="true">✓</div>
          <div className="min-w-0 flex-1">
            <b className="text-lg">今天沒有要決定的事</b>
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
            ? <SettleCard key={keyOf(d)} brandId={brandId} row={d.row} recovering={recovering} />
            : <DecisionCardFor key={keyOf(d)} brandId={brandId} item={d.item} recovering={recovering} />))}
        </div>
        {rest.length > 0 && (
          <Disclosure label={`還有 ${rest.length} 件要決定`}>
            {rest.map((d) => (d.kind === "settle"
              ? <SettleRow key={keyOf(d)} brandId={brandId} row={d.row} recovering={recovering} />
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
      {body}
    </section>
  );
}

/** Prototype `doneLabel(q)`: what was decided, in one line. */
function doneLabel(d: HomeDecision, rules: AdsRules | null): string {
  if (d.kind === "settle") return `結算上一期 ${settleRange(d.row)}`;
  const item = d.item;
  if (item.kind_key === "cleanup") return `清理：${decisionTitle(item)}`;
  if (item.kind_key === "worse") return `${moveText(item.triage.grade_move, rules)}：${item.triage.name ?? "未命名廣告"}`;
  return decisionTitle(item);
}

function HandledFold({ brandId, done, recovering }: { brandId: string; done: HomeDecision[]; recovering: boolean }) {
  const rules = useAdsRules();
  if (!done.length) return null;
  return (
    <Disclosure label={`今天處理過 ${done.length} 件`}>
      {done.map((d) => {
        const action = d.kind === "settle" ? settleAction(brandId, d.row) : homeAction(brandId, d.item);
        // drill-10 Q2: the chip opens the decision (a deferred one shows 「M/D 再看」 and leads back to its change set).
        return (
          <div key={keyOf(d)} className="flex flex-wrap items-center gap-3 border-t border-border py-2 first:border-t-0">
            <span className="min-w-0 flex-1 text-sm [overflow-wrap:anywhere]">{doneLabel(d, rules)}</span>
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
      <span className="min-w-0 truncate text-sm text-muted-foreground" title={campaign}>{shortName(campaign)}</span>
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

function DecisionCardFor(props: { brandId: string; item: QueueItem; recovering: boolean }) {
  if (props.item.kind_key === "cleanup") return <CleanupCard {...props} />;
  if (props.item.kind_key === "worse") return <WorseCard {...props} />;
  return <RefreshCard {...props} />;
}

function CleanupFigure({ ad, breakEven }: { ad: QueueCleanupAd; breakEven: number | null }) {
  if (ad.grade === "wasted") return <>花 {formatAmount(ad.spend) ?? "—"}・0 筆</>;
  if (ad.cost_per_result === null) return <>每筆 —</>;
  return (
    <>
      每筆 {wholeYuan(ad.cost_per_result)}
      <MoneyTag cost={ad.cost_per_result} breakEven={breakEven} className="block" />
    </>
  );
}

/** Prototype `cleanCard()`: the proposed cut, 沒賣出 first, with the daily saving when the last 7 days are known. */
function CleanupCard({ brandId, item, recovering }: { brandId: string; item: QueueItem; recovering: boolean }) {
  const cleanup = item.cleanup;
  const ads = cleanup?.ads ?? [];
  const red = ads.length > 0 && ads.every((a) => a.grade === "over" || a.grade === "wasted");
  const saving = cleanup?.daily_saving ?? null;
  const breakEven = item.triage.target.break_even ?? null;
  const title = ads.length
    ? `${red ? "關掉色帶裡紅色的" : "關掉"} ${ads.length} 則${saving === null ? "" : `，每天省約 ${formatAmount(Math.round(saving / 10) * 10)} 元`}`
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
                <CleanupFigure ad={ad} breakEven={breakEven} />
              </span>
            </div>
          ))}
        </div>
      )}
      {recovering ? <Recovering /> : <CardAction brandId={brandId} item={item} primary />}
    </article>
  );
}

/** Prototype `worseCard()`: 變貴 is the grade moving against this campaign's cap (`grade_move`); the week-over-week
 * trend is only the footnote. */
function WorseCard({ brandId, item, recovering }: { brandId: string; item: QueueItem; recovering: boolean }) {
  const t = item.triage;
  const rules = useAdsRules();
  const prev = t.previous.cost_per_result;
  const cur = t.current.cost_per_result;
  const cap = t.target.value;
  const who = shortName(t.campaign_name);
  const capWord = t.target.basis === "break_even"
    ? <>{who}暫用<Term k="break_even" value={t.target.break_even}>打平線</Term></>
    : <>{who}的<Term k="cap">上限</Term></>;
  const over = cap !== null && cur !== null && cur > cap;
  return (
    <article className={cn(CARD, "border-border")} aria-label={t.name ?? "未命名廣告"}>
      <CardHead label={moveText(t.grade_move, rules)} className="bg-zone-watch text-warning-strong" campaign={t.campaign_name} />
      <div className="text-base font-semibold [overflow-wrap:anywhere]">{t.name ?? "未命名廣告"}</div>
      <div>
        <div className="numeric text-base font-semibold [overflow-wrap:anywhere]">
          每筆 {prev !== null && `${perSaleAmount(prev)} → `}{perSaleAmount(cur) ?? "—"}
          {cap !== null && cur !== null && <>，{over ? "超過" : "還在"}{capWord} {formatAmount(cap)}{over ? "" : " 內"}</>}
        </div>
        <MoneyTag cost={cur} breakEven={t.target.break_even} className="block" />
        <div className="mt-1 text-xs text-muted-foreground">{trendNote(t)}（只當參考）</div>
      </div>
      <div className="flex-1" />
      {recovering ? <Recovering /> : <CardAction brandId={brandId} item={item} primary={false} />}
    </article>
  );
}

/** Not drawn by the prototype's home: the same card shape for a `refresh_creative` row (too few readable ads). */
function RefreshCard({ brandId, item, recovering }: { brandId: string; item: QueueItem; recovering: boolean }) {
  const refresh = item.refresh;
  const thumbs = refresh?.thumbnails.slice(0, 4) ?? [];
  return (
    <article className={cn(CARD, "border-border")} aria-label={decisionTitle(item)}>
      <CardHead label="素材不夠判讀" className="" campaign={refresh?.campaign_name ?? item.triage.campaign_name} />
      <div className="text-base font-semibold">{decisionTitle(item)}</div>
      <ThumbTiles items={thumbs} size={32} hollow={4 - thumbs.length} />
      <div className="flex-1" />
      {recovering ? <Recovering /> : <CardAction brandId={brandId} item={item} primary={false} />}
    </article>
  );
}
