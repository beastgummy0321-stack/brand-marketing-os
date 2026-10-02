import type { ReactNode } from "react";
import type { AbPair as AbPairView, AbSide } from "@/lib/adsAbApi";
import { cn } from "@/lib/utils";
import { Chip, formatAmount } from "./Chip";
import { Thumb } from "./LoopPieces";
import { MoneyTag } from "./MoneyTag";
import { perSaleAmount } from "./csv";

/** Kit piece for one automatic A/B pair (Feature F29 Contract F; prototype v10 `abPair()`, `.ab/.abt/.abk/.pb`).
 * Pure presentational: the pair comes from `GET …/ab-pairs` as is; the screen passes the action (關掉輸家 /
 * 繼續 / decided chip) that fits `pair.decision`. Unknown numbers (null) print as unknown, never 0.
 * `data-slot="ab-pair"`, `data-variant` = the pair state. */

const md = (iso: string) => iso.slice(5).replace("-", "/");
// F47-I06: the one per-sale rule (whole yuan, rounded, never floored).
const whole = perSaleAmount;

function Mark({ k }: { k: "A" | "B" }) {
  return <span className="inline-grid size-6 shrink-0 place-items-center rounded-md bg-foreground text-xs font-bold text-white">{k}</span>;
}

/** `.pb`: the fill is green when the side passed (or won); otherwise the collecting purple, or the judged loser's grey. */
function Progress({ value, max, ok, rest = "bg-chart-soft" }: { value: number | null; max: number; ok: boolean; rest?: string }) {
  const pct = value === null || max <= 0 ? 0 : Math.min(100, Math.max(0, (value / max) * 100));
  return (
    <div className="relative mt-1.5 h-2 overflow-hidden rounded bg-muted" aria-hidden="true">
      <i className={cn("absolute inset-y-0 left-0 rounded", ok ? "bg-success" : rest)} style={{ width: `${pct}%` }} />
    </div>
  );
}

function Gauge({ label, text, value, max, ok }: { label: string; text: string; value: number | null; max: number; ok: boolean }) {
  return (
    <div>
      <div className="flex justify-between gap-2">
        <span className="text-xs">{label}</span>
        <b className={cn("text-xs", ok && "text-success-strong")}>{text}</b>
      </div>
      <Progress value={value} max={max} ok={ok} />
    </div>
  );
}

function Tile({ k, side, dimension, win, verdict, max, breakEven }: {
  k: "A" | "B"; side: AbSide; dimension: string; win: boolean | null; verdict: boolean; max: number; breakEven: number | null;
}) {
  const cost = side.cost_per_result;
  return (
    <div className={cn("flex min-w-0 flex-col gap-2 rounded-[10px] border border-border p-3.5",
      win === true && "border-success bg-success/5 ring-1 ring-success", win === false && "bg-muted/40")}>
      <div className="flex items-center gap-2.5">
        <Mark k={k} />
        <Thumb url={side.thumbnail_url} size={36} />
        <div className="min-w-0">
          <div className="text-[11.5px] text-muted-foreground">{dimension}：{side.value_label}</div>
          <div className="text-xs font-medium [overflow-wrap:anywhere]">{side.name}</div>
        </div>
      </div>
      <div className="numeric">
        {cost === null
          ? <span className="text-sm font-medium text-muted-foreground">每筆讀不到</span>
          : <><span className="text-2xl font-[650] tracking-tight">{whole(cost)} 元</span> <span className="text-xs text-muted-foreground">每賣一筆</span><MoneyTag cost={cost} breakEven={breakEven} /></>}
      </div>
      <Progress value={cost} max={max} ok={win === true} rest="bg-chart-rest" />
      <div className="numeric flex justify-between gap-2 text-[11.5px] text-muted-foreground">
        <span>{side.results === null ? "購買讀不到" : `購買 ${formatAmount(side.results)} 筆 ✓`}</span>
        <span>{side.spend === null ? "花費讀不到" : `花 ${formatAmount(side.spend)} 元`}</span>
      </div>
      {verdict && win !== null && <Chip tone={win ? "ok" : "neutral"} className="self-start">{win ? "比較划算・留下" : "比較貴・建議關掉"}</Chip>}
    </div>
  );
}

export function AbPair({ pair, breakEven = null, action }: { pair: AbPairView; breakEven?: number | null; action?: ReactNode }) {
  const { a, b, rules, missing, window: win, days, dimension_label: dim } = pair;
  const title = <b>只差「{dim}」</b>;

  if (pair.state === "collecting") {
    const need = rules.min_conversions_each;
    const sideText = (r: number | null) => (r === null ? "讀不到" : r >= need ? `${r} 筆 ✓` : `${r}／${need} 筆`);
    const gaps = [
      missing.days > 0 ? `還差 ${missing.days} 天` : "",
      missing.a_results === null ? "A 的購買讀不到" : missing.a_results > 0 ? `A 還差 ${missing.a_results} 筆購買` : "",
      missing.b_results === null ? "B 的購買讀不到" : missing.b_results > 0 ? `B 還差 ${missing.b_results} 筆購買` : "",
    ].filter(Boolean).join("／");
    return (
      <div data-slot="ab-pair" data-variant="collecting">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          {title}<Chip>還不能判斷</Chip>
          <span className="text-[11.5px] text-muted-foreground">{win ? `${md(win.start)} 開始・第 ${days} 天` : pair.reason}</span>
        </div>
        <div className="mb-3 flex flex-wrap items-center gap-2.5">
          <Mark k="A" /><Thumb url={a.thumbnail_url} size={28} /><span className="text-xs">{dim}：{a.value_label}</span>
          <span className="text-xs text-muted-foreground">vs</span>
          <Mark k="B" /><Thumb url={b.thumbnail_url} size={28} /><span className="text-xs">{dim}：{b.value_label}</span>
        </div>
        <div className="grid grid-cols-3 gap-3.5">
          <Gauge label="投放天數" text={`${days}／${rules.min_days} 天`} value={days} max={rules.min_days} ok={days >= rules.min_days} />
          <Gauge label="A 的購買" text={sideText(a.results)} value={a.results} max={need} ok={a.results !== null && a.results >= need} />
          <Gauge label="B 的購買" text={sideText(b.results)} value={b.results} max={need} ok={b.results !== null && b.results >= need} />
        </div>
        {gaps && <div className="mt-3 font-semibold">{gaps}</div>}
      </div>
    );
  }

  if (pair.state === "unreadable") {
    return (
      <div data-slot="ab-pair" data-variant="unreadable">
        <div className="mb-2 flex flex-wrap items-center gap-2">{title}<Chip tone="warn">讀不到</Chip></div>
        {pair.reason && <div className="text-xs text-muted-foreground">{pair.reason}</div>}
      </div>
    );
  }

  const judged = pair.state === "judged" && pair.winner !== null;
  const costs = [a.cost_per_result, b.cost_per_result].filter((c): c is number => c !== null);
  const max = costs.length ? Math.max(...costs) * 1.15 : 0;
  const W = pair.winner === "a" ? "A" : "B";
  const diff = a.cost_per_result !== null && b.cost_per_result !== null ? Math.abs(a.cost_per_result - b.cost_per_result) : null;
  const pct = formatAmount(pair.difference_pct);
  const span = win ? `近 ${days} 天 ${md(win.start)}–${md(win.end)}・其他都一樣` : null;
  return (
    <div data-slot="ab-pair" data-variant={pair.state}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {title}{judged ? <Chip tone="ok">可以判斷了</Chip> : <Chip>差不多</Chip>}
        {span && <span className="text-[11.5px] text-muted-foreground">{span}</span>}
      </div>
      <div className="grid grid-cols-[minmax(0,1fr)_36px_minmax(0,1fr)] items-stretch gap-2.5">
        <Tile k="A" side={a} dimension={dim} win={judged ? pair.winner === "a" : null} verdict={judged} max={max} breakEven={breakEven} />
        <div className="grid place-items-center text-xs font-bold text-muted-foreground">vs</div>
        <Tile k="B" side={b} dimension={dim} win={judged ? pair.winner === "b" : null} verdict={judged} max={max} breakEven={breakEven} />
      </div>
      <div className="mt-3.5 flex flex-wrap items-center gap-3.5">
        <div className="min-w-[200px] flex-1">
          {judged ? (
            <>
              <b className="text-lg text-success-strong">{W} 比較划算</b>
              <div className="text-xs text-muted-foreground">
                {W} 每筆便宜 {pct === null ? "—" : `${pct}%`}{diff !== null && `（${formatAmount(Math.round(diff))} 元）`}，兩則都跑滿 {rules.min_days} 天、各賣到 {rules.min_conversions_each} 筆以上
              </div>
              <div className="text-xs text-muted-foreground">關掉不會刪除，想反悔隨時可以再開</div>
            </>
          ) : (
            <div className="text-xs text-muted-foreground">
              每筆只差 {pct === null ? "—" : `${pct}%`}，不到 {formatAmount(rules.relative_difference * 100)}%，兩則都留著
            </div>
          )}
        </div>
        {action && <div className="flex flex-wrap items-center gap-2">{action}</div>}
      </div>
    </div>
  );
}
