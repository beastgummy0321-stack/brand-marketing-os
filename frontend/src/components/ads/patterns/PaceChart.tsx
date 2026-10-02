import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { formatAmount } from "./Chip";

/** Kit pieces for the v9 home month cards (prototype `homeMoney()` pace chart and `homeNext()` strip).
 * Pure presentational; `data-slot` is what `frontend/scripts/ui-evidence.cjs` compares against the prototype. */

// Chart frame of the prototype's viewBox 0 0 580 220: x 40→540 over the month, y 190 (0) → 20 (month budget).
const X0 = 40, X1 = 540, Y0 = 190, Y1 = 20;

/** `.paceh` + the budget pace SVG: cumulative spend by day against the straight 「平均花完的速度」 line to the month
 * budget, today's marker and a dotted projection to month end. F47-I06: without a month budget above 0 (unset, or a
 * 0 stored before Contract A) there is no scale to draw on — the card says 「還沒設月預算」 and draws nothing (a 0
 * total used to divide by zero and paint NaN coordinates). */
export function PaceChart({ month, dayOfMonth, daysInMonth, budget, spent, daily, projected, title = "預算用了多少" }: {
  /** Month number printed on the axis (9 → 9/1 … 9/30). */
  month: number;
  dayOfMonth: number;
  daysInMonth: number;
  budget: number | null;
  spent: number | null;
  /** Cumulative spend at the end of each day so far (home overview `pace.daily`). */
  daily: { day: number; cumulative: number }[];
  projected: number | null;
  title?: string;
}) {
  if (budget === null || !(budget > 0)) {
    return (
      <div data-slot="pace-chart" className="min-w-0">
        <div className="mb-2"><b className="text-[15px] font-semibold">{title}</b></div>
        <p role="status" className="rounded-[10px] border border-dashed border-border px-4 py-10 text-center text-sm text-muted-foreground">
          還沒設月預算{spent !== null ? `・這個月已花 ${formatAmount(spent)}` : ""}
        </p>
      </div>
    );
  }
  const top = budget;
  const x = (day: number) => X0 + (Math.min(day, daysInMonth) / daysInMonth) * (X1 - X0);
  const y = (v: number) => Math.round(Y0 - ((Y0 - Y1) * Math.min(Math.max(v, 0), top)) / top);
  const points = [{ day: 0, cumulative: 0 }, ...daily.filter((d) => d.day <= dayOfMonth)].map((d) => `${x(d.day)},${y(d.cumulative)}`);
  const todayX = x(dayOfMonth);
  const todayY = spent === null ? null : y(spent);
  const pace = Math.round((budget * dayOfMonth) / daysInMonth);
  const label = `預算 ${formatAmount(budget)}，已花 ${formatAmount(spent) ?? "未知"}，照預算今天應花到 ${formatAmount(pace)}`;
  return (
    <div data-slot="pace-chart" className="min-w-0">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
        <b className="text-[15px] font-semibold">{title}</b>
        <span className="flex gap-4 text-xs text-muted-foreground">
          <span><span className="mr-1.5 inline-block h-[3px] w-3.5 bg-primary align-middle" />實際累計</span>
          <span><span className="mr-1.5 inline-block w-3.5 border-t-2 border-dashed border-chart-rest align-middle" />平均花完的速度</span>
        </span>
      </div>
      <svg width="100%" viewBox="0 0 580 220" role="img" aria-label={label} className="block">
        <line x1={X0} y1={Y0} x2={560} y2={Y0} className="stroke-border" />
        <line x1={X0} y1={Y1} x2={560} y2={Y1} className="stroke-muted" />
        <text x={44} y={14} fontSize={11} className="fill-muted-foreground">預算 {formatAmount(budget)}</text>
        <text x={30} y={194} textAnchor="end" fontSize={11} className="fill-muted-foreground">0</text>
        <line x1={X0} y1={Y0} x2={X1} y2={Y1} strokeWidth={2} strokeDasharray="5 5" className="stroke-chart-rest" data-part="pace-line" />
        {points.length > 1 && (
          <>
            <polygon points={`${points.join(" ")} ${x(daily.filter((d) => d.day <= dayOfMonth).at(-1)?.day ?? 0)},${Y0}`} fillOpacity={0.08} className="fill-primary" />
            <polyline points={points.join(" ")} fill="none" strokeWidth={3} strokeLinejoin="round" className="stroke-primary" data-part="actual-line" />
          </>
        )}
        {todayY !== null && projected !== null && (
          <polyline points={`${todayX},${todayY} ${X1},${y(projected)}`} fill="none" strokeWidth={2} strokeDasharray="2 5" className="stroke-primary" data-part="projection" />
        )}
        <line x1={todayX} y1={30} x2={todayX} y2={Y0} strokeWidth={1} className="stroke-foreground" />
        <text x={todayX} y={205} textAnchor="middle" fontSize={11} fontWeight={600} className="fill-foreground">今天 {month}/{dayOfMonth}</text>
        <text x={X0} y={205} textAnchor="middle" fontSize={11} className="fill-muted-foreground">{month}/1</text>
        <text x={X1} y={205} textAnchor="middle" fontSize={11} className="fill-muted-foreground">{month}/{daysInMonth}</text>
        {todayY !== null && (
          <>
            <circle cx={todayX} cy={todayY} r={5} className="fill-primary" />
            <text x={todayX - 11} y={todayY - 8} textAnchor="end" fontSize={13} fontWeight={600} className="fill-foreground">已花 {formatAmount(spent)}</text>
          </>
        )}
      </svg>
    </div>
  );
}

export type NextUpKind = "today" | "month_review" | "campaign_start" | "campaign_end";
export interface NextUpItem {
  key: string;
  kind: NextUpKind;
  /** e.g. 「9/23 今天」, 「10/01」. */
  date: string;
  body: ReactNode;
  /** campaign_start only: false draws the amber 「還沒準備好」 ring. */
  ready?: boolean | null;
}

const DOT: Record<NextUpKind, string> = {
  today: "bg-foreground",
  month_review: "bg-primary",
  campaign_start: "border-2 border-chart-soft bg-card",
  campaign_end: "border-2 border-input bg-card",
};

/** `.nextup`: 「接下來」 strip — up to four dated stops on one line (home overview `timeline`). */
export function NextUpStrip({ items, title = "接下來" }: { items: NextUpItem[]; title?: string }) {
  return (
    <section data-slot="next-up-strip" aria-label={title} className="surface flex items-center gap-6 px-6 py-3.5">
      <b className="shrink-0 text-sm font-semibold">{title}</b>
      <div className="relative grid min-w-0 flex-1 grid-cols-4 gap-3 before:absolute before:top-1.5 before:right-[12%] before:left-1.5 before:h-0.5 before:bg-border">
        {items.map((item) => (
          <div key={item.key} data-kind={item.kind} className="relative flex min-w-0 flex-col items-start gap-1.5 text-[13px]">
            <span className={cn("size-3.5 rounded-full", DOT[item.kind], item.kind === "campaign_start" && item.ready === false && "border-warning/80")} />
            <span className={cn("numeric text-xs", item.kind === "today" ? "font-semibold" : "text-muted-foreground")}>{item.date}</span>
            {item.body}
          </div>
        ))}
      </div>
    </section>
  );
}
