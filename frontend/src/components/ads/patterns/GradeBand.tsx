import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { GRADE_LABEL, formatAmount, type Grade } from "./Chip";
import { Term } from "./Term";

/** Kit piece for the money-quality band (prototype v10 `homeBand()`, `.bandc` + `.band`): how much of the month's
 * spend landed in each grade. Buckets come from the home overview `quality.buckets` and sum to `spent`
 * (Feature F28 "Home overview"); segment width is the bucket amount. `data-slot="grade-band"`. */

export interface BandAd { entity_id: string; name: string; thumbnail_url: string | null; spend: number | null }
export interface BandBucket { grade: Grade | "ungraded"; amount: number; count: number; ads: BandAd[] }

const SEGMENTS = [
  { grade: "on_target", box: "bg-success/10", text: "text-success", outline: "" },
  { grade: "watch", box: "bg-warning/10", text: "text-warning", outline: "" },
  { grade: "over", box: "bg-danger/10", text: "text-danger/90", outline: "outline-2 -outline-offset-2 outline-danger/65" },
  { grade: "wasted", box: "bg-danger/20", text: "text-danger", outline: "outline-2 -outline-offset-2 outline-danger" },
] as const;
const OK_THUMBS = [56, 50, 44, 38, 34, 30];
const ONE_THUMB = { watch: 38, over: 34, wasted: 30 } as const;
const HATCH = "bg-[repeating-linear-gradient(45deg,var(--color-border)_0_4px,var(--color-background)_4px_8px)]";
const short = (s: string, n: number) => (s.length > n ? `${s.slice(0, n)}…` : s);

export function GradeBand({ buckets, spent, spentLabel, cap }: {
  buckets: BandBucket[];
  /** The screen's one 已花 number; null = unknown (the percentage is then unknown too). */
  spent: number | null;
  /** e.g. 「9 月已花」. */
  spentLabel: string;
  /** One brand-level cap when every campaign shares it; null prints the per-campaign legend. */
  cap: { value: number; basis: "own" | "break_even" } | null;
}) {
  const of = (grade: BandBucket["grade"]) => buckets.find((b) => b.grade === grade);
  const okAmount = of("on_target")?.amount ?? 0;
  const pct = spent ? Math.round((okAmount / spent) * 100) : null;
  const thinAmount = of("insufficient")?.amount ?? 0;
  const ungradedAmount = buckets.filter((b) => b.grade === "ungraded" || b.grade === "no_target").reduce((s, b) => s + b.amount, 0);
  const rest = thinAmount + ungradedAmount;
  const T = cap?.value ?? null;

  const segments = SEGMENTS.flatMap((seg) => {
    const bucket = of(seg.grade);
    if (!bucket || (!bucket.count && !bucket.amount)) return [];
    const ads = bucket.ads.slice().sort((x, y) => (y.spend ?? 0) - (x.spend ?? 0));
    const amount = <span className="numeric whitespace-nowrap">{formatAmount(bucket.amount)} 元</span>;
    if (seg.grade === "on_target") {
      return [(
        <div key={seg.grade} data-grade={seg.grade} className={cn("flex min-w-[140px] flex-col justify-between overflow-hidden rounded p-3 first:rounded-l-[10px] last:rounded-r-[10px]", seg.box)} style={{ flex: `${bucket.amount} 1 0` }}>
          <div className={cn("flex justify-between gap-2", seg.text)}><b>{GRADE_LABEL.on_target}</b><span className="font-semibold">{amount}</span></div>
          <div className="flex items-end gap-1.5">
            {ads.slice(0, OK_THUMBS.length).map((a, i) => <Thumb key={a.entity_id} url={a.thumbnail_url} size={OK_THUMBS[i]} />)}
            <span className="ml-1.5 text-xs whitespace-nowrap text-muted-foreground">{bucket.count} 則</span>
          </div>
        </div>
      )];
    }
    const small = seg.grade === "wasted";
    const top = ads[0];
    return [(
      <div key={seg.grade} data-grade={seg.grade} className={cn("flex min-w-[72px] flex-col justify-between overflow-hidden rounded p-3 first:rounded-l-[10px] last:rounded-r-[10px]", small && "px-2 py-2.5", seg.box, seg.outline)} style={{ flex: `${bucket.amount} 1 0` }}>
        <div className={seg.text}>
          <b className={cn(small && "text-[13px]")}>{GRADE_LABEL[seg.grade]}</b>
          <div className={cn(small ? "text-xs" : "text-[13px]")}>{amount}</div>
        </div>
        <div className="flex flex-col gap-1">
          {top && <Thumb url={top.thumbnail_url} size={ONE_THUMB[seg.grade]} />}
          <span className={cn("text-[11px] leading-snug [overflow-wrap:anywhere]", seg.text)}>{bucket.count > 1 || !top ? `${bucket.count} 則` : short(top.name, 6)}</span>
        </div>
      </div>
    )];
  });
  if (rest > 0) segments.push(<div key="rest" data-grade="rest" className={cn("min-w-2.5 rounded p-0 first:rounded-l-[10px] last:rounded-r-[10px]", HATCH)} style={{ flex: `${rest} 1 0` }} title={`剛開始、數字還不夠或未分級 ${formatAmount(rest)} 元`} />);

  const legend = (swatch: string, label: ReactNode) => (
    <span><span className={cn("mr-1.5 inline-block size-2.5 rounded-[3px] align-[-1px]", swatch)} />{label}</span>
  );

  return (
    <div data-slot="grade-band" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline gap-3.5">
        <span className={cn("numeric text-4xl leading-tight font-semibold tracking-tight", pct === null ? "text-muted-foreground" : "text-success")}>{pct === null ? "—" : `${pct}%`}</span>
        <span className="text-[17px] font-medium">的廣告費花得划算</span>
        <span className="numeric ml-auto text-[13px] text-muted-foreground">{spentLabel} {spent === null ? "未知" : `${formatAmount(spent)} 元`}</span>
      </div>
      <div className="flex h-32 gap-1">
        {segments.length ? segments : <div className={cn("flex-1 rounded-[10px]", HATCH)} aria-label="還沒有花費" />}
      </div>
      {/* v10 `homeBand()` legend: every grade word is a glossary `Term` (the sentence lives in glossary.ts); the
          shared cap's values follow in brackets only when every campaign has the same one. */}
      <div data-part="band-legend" className="flex flex-wrap gap-x-5 gap-y-1.5 text-xs text-muted-foreground">
        <span>每個活動對照自己的上限：</span>
        {legend("border border-success bg-success/10", <><Term k="on_target">划算</Term>＝每筆沒超過<Term k="cap">上限</Term>{T !== null && `（${formatAmount(T)}）`}</>)}
        {legend("border border-warning/80 bg-warning/10", <><Term k="watch">偏貴</Term>＝超過上限不到 2 成{T !== null && `（${formatAmount(T)}–${formatAmount(T * 1.2)}）`}</>)}
        {legend("border border-danger bg-danger/10", <><Term k="over">太貴</Term>＝超過 2 成以上{T !== null && `（${formatAmount(T * 1.2)} 以上）`}</>)}
        {legend("border border-danger bg-danger/20", <><Term k="wasted">沒賣出</Term>＝花了錢一筆都沒賣</>)}
        {legend("bg-muted", <><Term k="thin">剛開始、數字還不夠</Term> {formatAmount(thinAmount)} 元</>)}
        {ungradedAmount > 0 && legend(HATCH, `未分級 ${formatAmount(ungradedAmount)} 元`)}
      </div>
    </div>
  );
}

function Thumb({ url, size }: { url: string | null; size: number }) {
  const style = { width: size, height: size };
  return url
    ? <img src={url} alt="" className="shrink-0 rounded-lg object-cover" style={style} />
    : <span className="shrink-0 rounded-lg bg-card/70" style={style} aria-hidden="true" />;
}
