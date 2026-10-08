import type { HomeOverview } from "@/lib/adsHomeApi";
import { cn } from "@/lib/utils";
import { formatAmount } from "../patterns";
import { money, weekBars, type WeekBar } from "./monthCsv";

const HATCH = "bg-[repeating-linear-gradient(45deg,var(--color-border)_0_4px,var(--color-background)_4px_8px)]";
const CHART_H = 150;

export function WeeklySpend({ home }: { home: HomeOverview }) {
  const pace = home.pace;
  const budget = pace?.budget_amount ?? null;
  const comparable = !!home.currency && home.currency === pace?.budget_currency && pace.budget_comparison?.reason === null;
  const bars: WeekBar[] = pace ? weekBars(home.month, home.days_in_month, pace.daily, budget, comparable) : [];
  const top = Math.max(1, ...bars.flatMap((w) => [w.spend, w.pace].filter((v): v is number => v !== null))) * 1.1;
  const px = (v: number) => Math.round((v / top) * CHART_H);
  const cols = { gridTemplateColumns: `repeat(${Math.max(bars.length, 1)}, minmax(0, 1fr))` };
  return (
    <section aria-label="每週花費 vs 預算步調" data-part="weekly-spend" className="surface px-[22px] py-5">
      <div className="mb-3.5 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-[15px] font-semibold">每週花費 vs 預算步調</h2>
        <div className="flex flex-wrap items-center gap-3.5">
          <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-muted-foreground">
            <span><i aria-hidden="true" className="mr-[5px] inline-block size-2 rounded-[2px] bg-primary" />花費</span>
            {budget === null
              ? <span>沒設月預算，不畫步調</span>
              : !comparable ? <span>已設月預算 {money(budget, pace?.budget_currency)}</span> : <span><i aria-hidden="true" className="mr-[5px] inline-block w-3.5 border-t-2 border-dashed border-chart-rest align-middle" />月預算 {money(budget, pace?.budget_currency)} 的步調</span>}
          </div>
          <b className="numeric font-semibold">已花 {money(home.spent, home.currency)}</b>
        </div>
      </div>
      {pace && <p className="mb-2 text-xs text-muted-foreground">預算可用餘額 {money(pace.available, pace.budget_currency)}</p>}
      {pace === null ? <p className="text-sm text-muted-foreground">這個月的每日花費讀不到，其他區塊照常。</p> : budget !== null && !comparable ? <div className="flex min-h-[210px] items-center justify-center text-sm text-muted-foreground">{pace.budget_comparison?.reason === "currency_mismatch" ? "月預算與廣告花費幣別不同" : "幣別尚未確認"}，暫不比較花費進度</div> : !home.currency ? <p className="min-h-[210px] py-10 text-sm text-muted-foreground">廣告花費幣別尚未確認，暫不畫金額圖</p> : (
        <>
          <div className="relative grid h-[190px] items-end gap-[18px] border-b border-border px-1.5 max-md:gap-1.5" style={cols}>
            {bars.map((w) => (
              <div key={w.label} data-week={w.state} className="relative flex h-full flex-col items-center justify-end">
                {w.state === "known" ? (
                  <>
                    <span className="numeric mb-1 text-xs font-semibold">{money(w.spend, home.currency)}</span>
                    <div className="w-[56%] max-w-16 rounded-t-md bg-primary" style={{ height: Math.max(0, px(w.spend as number)) }} />
                  </>
                ) : (
                  <>
                    <span className="mb-1 text-xs text-muted-foreground">{w.state === "future" ? "還沒到" : "未知"}</span>
                    <div className={cn("w-[56%] max-w-16 rounded-t-md", HATCH)} style={{ height: 6 }} />
                  </>
                )}
                {w.pace !== null && (
                  <span
                    aria-hidden="true" title={`預算步調 ${formatAmount(Math.round(w.pace))}`}
                    className="absolute inset-x-[10%] border-t-2 border-dashed border-chart-rest" style={{ bottom: Math.max(0, px(w.pace)) }}
                  />
                )}
              </div>
            ))}
          </div>
          <div className="grid gap-[18px] px-1.5 pt-1.5 text-center text-xs text-muted-foreground max-md:gap-1.5" style={cols}>
            {bars.map((w) => (
              <span key={w.label}>{w.label}{w.through && <><br /><span className="text-[11.5px]">{w.through}</span></>}</span>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
