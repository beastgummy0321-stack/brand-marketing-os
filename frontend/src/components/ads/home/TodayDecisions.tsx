import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { Skeleton } from "@/components/layout/Skeleton";
import type { QueueCleanupAd, QueueItem, QueueKind, QueuePayload } from "@/lib/adsTriageApi";
import { Chip, Disclosure, GradeChip, ResultHero, ThumbTiles, formatAmount } from "../patterns";
import { cn } from "@/lib/utils";
import { wholeYuan } from "./MonthMoney";
import { shortName } from "./NextDates";
import { QueueRow, decisionTitle, homeAction } from "./QueueRow";

/** Board D 「需要你決定」 (prototype v9 `homeDecide()`): the brand queue's open `cleanup`, `worse` and
 * `refresh_creative` rows, in that order; three as cards, the rest behind one fold; decisions already handled
 * behind a second fold. The queue is its own request: loading, syncing and failure only change this block. */

export type QueueState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; queue: QueuePayload };

const ORDER: QueueKind[] = ["cleanup", "worse", "refresh_creative"];
const SHOWN = 3;

/** The home decisions of a queue, split into open and handled, in board order. */
export function homeDecisions(brandId: string, queue: QueuePayload): { open: QueueItem[]; done: QueueItem[] } {
  const rows = queue.items
    .filter((item) => ORDER.includes(item.kind_key))
    .map((item, i) => ({ item, i }))
    .sort((a, b) => ORDER.indexOf(a.item.kind_key) - ORDER.indexOf(b.item.kind_key) || a.i - b.i)
    .map(({ item }) => item);
  return {
    open: rows.filter((item) => !homeAction(brandId, item).done),
    done: rows.filter((item) => homeAction(brandId, item).done),
  };
}

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
  const decisions = state.status === "ready" ? homeDecisions(brandId, state.queue) : null;
  const open = decisions?.open ?? [];
  const done = decisions?.done ?? [];
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
          {shown.map((item, i) => <DecisionCardFor key={item.id} brandId={brandId} item={item} primary={i === 0} recovering={recovering} />)}
        </div>
        {rest.length > 0 && (
          <Disclosure label={`還有 ${rest.length} 件要決定`}>
            {rest.map((item) => <QueueRow key={item.id} brandId={brandId} item={item} recovering={recovering} />)}
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

function HandledFold({ brandId, done, recovering }: { brandId: string; done: QueueItem[]; recovering: boolean }) {
  if (!done.length) return null;
  return (
    <Disclosure label={`處理過 ${done.length} 件`}>
      {done.map((item) => <QueueRow key={item.id} brandId={brandId} item={item} recovering={recovering} />)}
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

function CardAction({ brandId, item, primary, recovering }: { brandId: string; item: QueueItem; primary: boolean; recovering: boolean }) {
  const action = homeAction(brandId, item);
  if (recovering) return <Chip className="self-start">補完資料後更新</Chip>;
  if (!action.href) return null;
  return (
    <Button asChild variant={primary ? "default" : "outline"} className="h-10 w-full">
      <Link to={action.href}>{action.label} →</Link>
    </Button>
  );
}

function Thumb({ url, size }: { url: string | null; size: number }) {
  const style = { width: size, height: size };
  return url
    ? <img src={url} alt="" className="shrink-0 rounded-lg object-cover" style={style} />
    : <span className="shrink-0 rounded-lg bg-muted" style={style} aria-hidden="true" />;
}

function DecisionCardFor(props: { brandId: string; item: QueueItem; primary: boolean; recovering: boolean }) {
  if (props.item.kind_key === "cleanup") return <CleanupCard {...props} />;
  if (props.item.kind_key === "worse") return <WorseCard {...props} />;
  return <RefreshCard {...props} />;
}

function cleanupFigure(ad: QueueCleanupAd): string {
  if (ad.grade === "wasted") return `花 ${formatAmount(ad.spend) ?? "—"}・0 筆`;
  return ad.cost_per_result === null ? "每筆 —" : `每筆 ${wholeYuan(ad.cost_per_result)}`;
}

/** Prototype `cleanCard()`: the proposed cut, 沒賣出 first, with the daily saving when the last 7 days are known. */
function CleanupCard({ brandId, item, primary, recovering }: { brandId: string; item: QueueItem; primary: boolean; recovering: boolean }) {
  const cleanup = item.cleanup;
  const ads = cleanup?.ads ?? [];
  const red = ads.length > 0 && ads.every((a) => a.grade === "over" || a.grade === "wasted");
  const saving = cleanup?.daily_saving ?? null;
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
              <GradeChip grade={ad.grade} />
              <span className="numeric min-w-[92px] text-right text-sm whitespace-nowrap text-muted-foreground">{cleanupFigure(ad)}</span>
            </div>
          ))}
        </div>
      )}
      <CardAction brandId={brandId} item={item} primary={primary} recovering={recovering} />
    </article>
  );
}

/** Prototype `worseCard()`: the ad got more expensive than the window before; compared with the campaign's cap. */
function WorseCard({ brandId, item, primary, recovering }: { brandId: string; item: QueueItem; primary: boolean; recovering: boolean }) {
  const t = item.triage;
  const prev = t.previous.cost_per_result;
  const cur = t.current.cost_per_result;
  const cap = t.target.value;
  const pct = cap && cur !== null ? Math.round(((cur - cap) / cap) * 100) : null;
  const ref = t.target.basis === "break_even" ? "打平" : "上限";
  const since = t.window.days === 7 ? "比上週變貴" : `比前 ${t.window.days} 天變貴`;
  return (
    <article className={cn(CARD, "border-border")} aria-label={t.name ?? "未命名廣告"}>
      <CardHead label={since} className="bg-zone-watch text-warning" campaign={t.campaign_name} />
      <div className="text-base font-semibold [overflow-wrap:anywhere]">{t.name ?? "未命名廣告"}</div>
      <div className="numeric flex flex-wrap items-baseline gap-2.5">
        <span className="text-[13px] text-muted-foreground">每筆</span>
        {prev !== null && <span className="text-sm text-chart-rest line-through">{formatAmount(Math.floor(prev))}</span>}
        <span className="text-xl font-semibold">{cur === null ? "—" : `→ ${wholeYuan(cur)}`}</span>
        {pct !== null && (pct > 0
          ? <span className="text-sm text-warning">比{ref}貴 {pct}%</span>
          : <span className="text-sm text-success">還在{ref}內</span>)}
      </div>
      <div className="flex-1" />
      <CardAction brandId={brandId} item={item} primary={primary} recovering={recovering} />
    </article>
  );
}

/** Not drawn by the prototype's home: the same card shape for a `refresh_creative` row (too few readable ads). */
function RefreshCard({ brandId, item, primary, recovering }: { brandId: string; item: QueueItem; primary: boolean; recovering: boolean }) {
  const refresh = item.refresh;
  const thumbs = refresh?.thumbnails.slice(0, 4) ?? [];
  return (
    <article className={cn(CARD, "border-border")} aria-label={decisionTitle(item)}>
      <CardHead label="素材不夠判讀" className="" campaign={refresh?.campaign_name ?? item.triage.campaign_name} />
      <div className="text-base font-semibold">{decisionTitle(item)}</div>
      <ThumbTiles items={thumbs} size={32} hollow={4 - thumbs.length} />
      <div className="flex-1" />
      <CardAction brandId={brandId} item={item} primary={primary} recovering={recovering} />
    </article>
  );
}
