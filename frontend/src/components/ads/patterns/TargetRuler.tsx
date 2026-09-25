import { useLayoutEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { GRADE_FILL, GRADE_LABEL, formatAmount, type Grade } from "./Chip";

/** Kit piece for the v9 target ruler (prototype `ruler()`, the signature visual of F28). Pure presentational:
 * every ad arrives already graded by the API (Feature F28 "Grades"); the ruler only places it.
 * `data-slot="target-ruler"` + `data-variant` = size (or `empty`) is what `frontend/scripts/ui-evidence.cjs`
 * compares against the prototype's `.rl.rl-<size>`. */

export interface RulerAd {
  id: string;
  name: string;
  grade: Grade;
  /** API `grade_label`; defaults to the grade's word. */
  gradeLabel?: string | null;
  costPerResult: number | null;
  spend: number | null;
  thumbnailUrl?: string | null;
  /** Trend note under the tooltip (prototype `trend()`, e.g. 「比前 14 天 ▲12%」). */
  note?: string | null;
}

export interface RulerCap {
  value: number;
  basis: "own" | "break_even";
}

export type RulerSize = "mini" | "mid" | "full";

const GEOMETRY = {
  mini: { dot: 10, step: 7, gapPct: 3.4, top: 16, box: 30 },
  mid: { dot: 14, step: 13, gapPct: 2.6, top: 20, box: 46 },
  full: { dot: 30, step: 33, gapPct: 4.8, top: 20, box: 64 },
} as const;

const RING: Record<Grade, string> = {
  on_target: "ring-success",
  watch: "ring-warning/80",
  over: "ring-danger/65",
  wasted: "ring-danger",
  insufficient: "ring-muted-foreground/30",
  no_target: "ring-chart-rest",
};

const SUMMARY_ORDER: Grade[] = ["wasted", "over", "watch", "on_target", "insufficient"];
const ON_AXIS = new Set<Grade>(["on_target", "watch", "over"]);

/** The axis the prototype computes: it runs to 1.6 × cap, or further when an ad costs more (+8% headroom);
 * `pos` is a left offset in percent, clamped to the axis end. */
export function rulerScale(cap: number, costs: number[]) {
  const max = Math.max(cap * 1.6, ...costs.map((c) => c * 1.08));
  return { max, pos: (v: number) => (Math.min(v, max) / max) * 100 };
}

const text = (v: number | null | undefined) => formatAmount(v) ?? "未知";

export function TargetRuler({ ads, cap, breakEven = null, size = "full", highlight, tray = true, onAdClick, emptyText = "沒設上限，先不分等級" }: {
  ads: RulerAd[];
  /** The campaign's resolved cap (`cap.value` + `cap.basis`); null draws the empty state. */
  cap: RulerCap | null;
  /** Product break-even; drawn as a dashed 打平 mark only beside an own cap that differs from it. */
  breakEven?: number | null;
  size?: RulerSize;
  /** `close` badges the ads a cleanup closes (mini: red ring, others dimmed); `scale`/`self` ring the set and dim the rest. */
  highlight?: { mode: "close" | "scale" | "self"; ids: string[] };
  tray?: boolean;
  onAdClick?: (id: string) => void;
  emptyText?: string;
}) {
  const g = GEOMETRY[size];
  const mini = size === "mini";

  if (!cap) {
    return (
      <div data-slot="target-ruler" data-variant="empty" role="img" aria-label={emptyText}>
        <div style={{ height: g.top }} />
        <div className="h-2.5 rounded-lg bg-[repeating-linear-gradient(45deg,var(--color-border)_0_4px,var(--color-background)_4px_8px)]" />
        {!mini && <div className="relative h-[18px] pt-[3px] text-[11.5px] font-semibold text-muted-foreground">{emptyText}</div>}
      </div>
    );
  }

  const T = cap.value;
  const capWord = cap.basis === "break_even" ? (mini ? "暫用" : "暫用打平") : "上限";
  const onAxis = ads.filter((a) => ON_AXIS.has(a.grade) && a.costPerResult !== null);
  const wasted = ads.filter((a) => a.grade === "wasted");
  const thin = ads.filter((a) => a.grade === "insufficient");
  const { pos } = rulerScale(T, onAxis.map((a) => a.costPerResult as number));

  // Dot plot: a dot that would overlap its left neighbour moves up one level.
  const levels: number[] = [];
  const placed = onAxis
    .slice()
    .sort((x, y) => (x.costPerResult as number) - (y.costPerResult as number))
    .map((a) => {
      const p = pos(a.costPerResult as number);
      let level = 0;
      while (levels[level] !== undefined && p - levels[level] < g.gapPct) level++;
      levels[level] = p;
      return { a, p, level };
    });
  const fieldHeight = g.top + Math.max(levels.length, 1) * g.step + (g.dot - g.step) + 6;
  const markBottom = mini ? 0 : 18;
  const showBreakEven = cap.basis === "own" && breakEven !== null && Math.abs(breakEven - T) > 0.01;
  const inSet = (id: string) => highlight?.ids.includes(id) ?? false;

  const dot = (a: RulerAd, p: number | null, level: number) => {
    const label = a.gradeLabel || GRADE_LABEL[a.grade];
    const closing = highlight?.mode === "close" && inSet(a.id);
    const ringed = highlight && highlight.mode !== "close" && inSet(a.id);
    const dim = highlight && (highlight.mode === "close" ? mini && !closing : !inSet(a.id));
    const style = p === null
      ? { position: "relative" as const, width: g.dot, height: g.dot }
      : { left: `${p}%`, bottom: level * g.step, width: g.dot, height: g.dot, marginLeft: -g.dot / 2 };
    const body = mini || size === "mid"
      ? <span className={cn("block size-full rounded-full border-2 border-card", GRADE_FILL[a.grade], closing && mini && "ring-2 ring-danger ring-offset-1 ring-offset-card", ringed && "ring-2 ring-primary ring-offset-2 ring-offset-card")} />
      : <Thumb url={a.thumbnailUrl} className={cn("size-full rounded-full ring-2 ring-offset-2 ring-offset-card", ringed ? "ring-primary shadow-[0_0_0_8px_var(--color-accent)]" : RING[a.grade])} />;
    const common = cn("absolute z-[2] rounded-full p-0", dim && "opacity-35"); // box dots: inline position:relative wins
    if (mini) return <span key={a.id} className={common} style={style} aria-hidden="true" data-grade={a.grade}>{body}</span>;
    const tipSide = p === null || p > 70 ? "right-[-4px]" : p < 22 ? "left-[-4px]" : "left-1/2 -translate-x-1/2";
    const facts = a.grade === "wasted"
      ? `花 ${text(a.spend)} 元・0 筆購買・白花線 ${formatAmount(3 * T)} 元`
      : `每筆 ${text(a.costPerResult)} 元・${label}`;
    const aria = `${a.name}｜${a.grade === "wasted" ? `花 ${text(a.spend)} 元・0 筆購買` : `每筆 ${text(a.costPerResult)} 元`}｜${label}`;
    return (
      <button key={a.id} type="button" className={cn(common, "group")} style={style} aria-label={aria} data-grade={a.grade} onClick={onAdClick ? () => onAdClick(a.id) : undefined}>
        {body}
        {closing && <em className="absolute -top-[7px] -right-[7px] grid h-[18px] min-w-[18px] place-items-center rounded-[9px] border-2 border-card bg-danger px-1 text-[10.5px] font-bold text-white not-italic">關</em>}
        <span className={cn("pointer-events-none absolute bottom-[calc(100%+10px)] z-[9] hidden w-max max-w-[260px] rounded-lg bg-foreground px-[11px] py-2 text-left text-xs leading-normal font-normal text-white group-hover:block group-focus-visible:block", tipSide)}>
          <b className="font-semibold">{a.name}</b><br />{facts}{a.note && <><br />{a.note}</>}
        </span>
      </button>
    );
  };

  const counts = SUMMARY_ORDER.filter((grade) => ads.some((a) => a.grade === grade))
    .map((grade) => `${GRADE_LABEL[grade]} ${ads.filter((a) => a.grade === grade).length}`).join("、");
  const capLabel = `${cap.basis === "break_even" ? "暫用打平" : "上限"} ${formatAmount(T)}`;
  const thinGroups = [...new Set(thin.map((a) => a.gradeLabel || GRADE_LABEL.insufficient))];

  return (
    <div data-slot="target-ruler" data-variant={size}>
      <div className="flex items-stretch gap-2" role="group" aria-label={`對照上限：${capLabel}；${counts}`}>
        <div className="relative min-w-0 flex-1">
          <div className="relative" style={{ height: fieldHeight }}>{placed.map((x) => dot(x.a, x.p, x.level))}</div>
          <div className="flex h-2.5 overflow-hidden rounded-[5px]" aria-hidden="true">
            <i className={cn("block h-full", GRADE_FILL.on_target)} style={{ width: `${pos(T)}%` }} />
            <i className={cn("block h-full", GRADE_FILL.watch)} style={{ width: `${pos(T * 1.2) - pos(T)}%` }} />
            <i className={cn("block h-full flex-1", GRADE_FILL.over)} />
          </div>
          {!mini && <ZoneLabels starts={[0, pos(T) + 1, pos(T * 1.2) + 1]} />}
          {showBreakEven && (
            <Mark at={pos(breakEven as number)} bottom={markBottom} side={(breakEven as number) < T ? "left" : "right"} dashed label={mini ? null : `打平 ${formatAmount(breakEven)}`} />
          )}
          <Mark at={pos(T)} bottom={markBottom} side={showBreakEven && (breakEven as number) > T ? "left" : "right"} label={`${capWord} ${formatAmount(T)}`} />
        </div>
        <div className="relative flex shrink-0 flex-col items-center justify-end gap-1 rounded-lg border border-dashed border-danger/45 bg-danger/10 pt-1 pb-[22px]" style={{ width: g.box }}>
          {wasted.map((a) => dot(a, null, 0))}
          {!wasted.length && !mini && <span className="mb-1 text-[11.5px] text-muted-foreground">無</span>}
          <em className="absolute inset-x-0 bottom-[3px] text-center text-[11.5px] font-bold text-danger not-italic">{mini ? "白" : "白花"}</em>
        </div>
      </div>
      {tray && thin.length > 0 && (mini ? (
        <div className="mt-1.5 flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
          還太新 {thin.length} 則 {thin.map((a) => <span key={a.id} className={cn("inline-block size-2 rounded-full", GRADE_FILL.insufficient)} />)}
        </div>
      ) : (
        <div className="mt-3 flex flex-wrap items-center gap-x-3.5 gap-y-2 rounded-[10px] bg-muted px-3 py-2.5" data-part="tray">
          {thinGroups.map((word) => {
            const group = thin.filter((a) => (a.gradeLabel || GRADE_LABEL.insufficient) === word);
            return [
              <span key={`h-${word}`} className="text-xs font-semibold text-muted-foreground">{word} {group.length} 則</span>,
              ...group.map((a) => {
                const gate = 3 * T;
                const pct = a.spend === null ? null : Math.round((a.spend / gate) * 100);
                return (
                  <div key={a.id} className="flex max-w-[280px] min-w-[180px] flex-1 items-center gap-2">
                    <Thumb url={a.thumbnailUrl} className="size-[26px] rounded-lg" />
                    <div className="min-w-0 flex-1">
                      <div className="text-[11.5px] font-medium [overflow-wrap:anywhere]">{a.name}</div>
                      {a.spend !== null && (
                        <div className="relative mt-[3px] mb-0.5 h-1.5 rounded-[5px] bg-card" aria-hidden="true">
                          <i className="absolute inset-y-0 left-0 rounded-[5px] bg-chart-rest" style={{ width: `${Math.min(100, pct as number)}%` }} />
                        </div>
                      )}
                      <div className="numeric flex justify-between gap-2 text-[11.5px] text-muted-foreground">
                        <span>已花 {text(a.spend)}／{formatAmount(gate)} 元</span>{pct !== null && <span>{pct}%</span>}
                      </div>
                    </div>
                  </div>
                );
              }),
            ];
          })}
        </div>
      ))}
    </div>
  );
}

const ZONE_WORDS = [
  { word: "划算", cls: "text-success" },
  { word: "偏貴", cls: "text-warning" },
  { word: "太貴", cls: "text-danger/90" },
] as const;
const ZONE_GAP = 6;

/** Where the zone words go on a row `width` px wide. Each word starts at its zone's start (`starts`, px); a word that
 * would run into the one before it moves right just past it (it stays inside its own zone or the next, never on top of
 * another word). The axis caption is right-aligned and only shown when it clears the last word. */
export function zoneLabelLayout(width: number, starts: number[], widths: number[], captionWidth: number, gap = ZONE_GAP) {
  const lefts: number[] = [];
  let edge = Number.NEGATIVE_INFINITY;
  starts.forEach((start, i) => {
    const left = Math.max(start, edge + gap);
    lefts.push(left);
    edge = left + widths[i];
  });
  return { lefts, caption: width - captionWidth >= edge + gap };
}

/** The zone-word row under the track (prototype `.rl .zl`). The prototype places the words by percent only, which
 * collides in narrow rulers (the strategy tab at 1024 px); here the row measures itself and applies `zoneLabelLayout`.
 * Before the first measurement (or without layout, e.g. jsdom) the words keep the prototype's percent positions. */
function ZoneLabels({ starts }: { starts: number[] }) {
  const row = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [layout, setLayout] = useState<{ lefts: number[]; caption: boolean } | null>(null);
  useLayoutEffect(() => {
    const el = row.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => setWidth(el.clientWidth));
    observer.observe(el);
    setWidth(el.clientWidth);
    return () => observer.disconnect();
  }, []);
  const key = starts.join(",");
  useLayoutEffect(() => {
    const el = row.current;
    if (!el || !width) { setLayout(null); return; }
    const spans = [...el.querySelectorAll<HTMLElement>("[data-zone]")];
    const caption = el.querySelector<HTMLElement>("[data-part='axis-caption']");
    setLayout(zoneLabelLayout(width, starts.map((pct) => (pct / 100) * width), spans.map((sp) => sp.offsetWidth), caption?.offsetWidth ?? 0));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `key` names `starts` by value.
  }, [width, key]);
  return (
    <div ref={row} className="relative h-[18px] text-[11.5px] font-semibold" aria-hidden="true">
      {ZONE_WORDS.map(({ word, cls }, i) => (
        <span
          key={word}
          data-zone={word}
          className={cn("absolute top-[3px] whitespace-nowrap", cls)}
          style={{ left: layout ? `${layout.lefts[i]}px` : `${starts[i]}%` }}
        >
          {word}
        </span>
      ))}
      <span
        data-part="axis-caption"
        className={cn("absolute top-[3px] right-0 whitespace-nowrap font-medium text-muted-foreground", layout && !layout.caption && "invisible")}
      >
        每賣一筆花多少 →
      </span>
    </div>
  );
}

function Mark({ at, bottom, side, dashed = false, label }: { at: number; bottom: number; side: "left" | "right"; dashed?: boolean; label: string | null }) {
  return (
    <div
      data-part={dashed ? "break-even-mark" : "cap-mark"}
      className={cn("absolute top-0 z-[1] w-0 border-l-2", dashed ? "border-dashed border-warning/80" : "border-foreground")}
      style={{ left: `${at}%`, bottom }}
    >
      {label && (
        <span className={cn("absolute -top-px text-[11.5px] leading-none font-semibold whitespace-nowrap", side === "left" ? "right-1" : "left-1", dashed && "text-warning")}>{label}</span>
      )}
    </div>
  );
}

/** Ad image, or a neutral placeholder when there is none or it fails to load (Meta image URLs expire), so an expired
 * URL never shows the browser's broken-image icon. */
function Thumb({ url, className }: { url?: string | null; className?: string }) {
  const [failed, setFailed] = useState<string | null>(null);
  return url && failed !== url
    ? <img src={url} alt="" className={cn("block object-cover", className)} onError={() => setFailed(url)} />
    : <span className={cn("block bg-border", className)} aria-hidden="true" data-part="thumb-placeholder" />;
}
