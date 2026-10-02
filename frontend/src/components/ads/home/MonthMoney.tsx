import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { Skeleton } from "@/components/layout/Skeleton";
import type { HomeCampaign, HomeEarnMissing, HomeOverview } from "@/lib/adsHomeApi";
import { MonthlyBudgetPanel } from "../MonthlyBudgetPanel";
import { MoneyMeter, MoneyTag, PaceChart, Term, formatAmount } from "../patterns";
import { cn } from "@/lib/utils";

/** Home money card (prototype v10 `homeMoney()`, `.moneyg`): what the month earned after ad cost, the cost per
 * purchase against the one shared cap, purchases against the same days of last month, and the budget pace chart
 * with the 調整 entry to the existing monthly-budget editor. Every number comes from `GET …/home` (F28-I06);
 * `null` prints the unknown text, never 0. */

/** `TWD` → `NT$`; any other currency code is printed as-is; unknown currency prints the bare number. */
export function currencyPrefix(currency: string | null): string {
  if (currency === "TWD") return "NT$";
  return currency ? `${currency} ` : "";
}

/** The prototype's `yuan()`: a cost per purchase as whole yuan (「139 元」). */
export function wholeYuan(value: number): string {
  return `${formatAmount(Math.floor(value))} 元`;
}

/** `YYYY-MM` → month number; falls back to the local month when absent. */
export function monthNumber(month: string | null | undefined): number {
  const m = month ? Number(month.split("-")[1]) : NaN;
  return Number.isFinite(m) ? m : new Date().getMonth() + 1;
}

const EARN_MISSING: Record<HomeEarnMissing, string> = {
  product_cost: "缺商品成本",
  product: "缺商品",
  spend: "缺花費資料",
  purchases: "缺購買資料",
  no_purchase_campaign: "沒有以購買為成果的活動",
};

/** v10 cap wording: caps are per campaign, so home never says 「你的上限」 as if it were one rule. A shared cap says
 * every campaign currently has the same one; none shared says they differ (or that none has one). */
function capText(home: HomeOverview): ReactNode {
  const cap = home.money?.cap ?? null;
  if (cap) {
    return cap.basis === "break_even"
      ? <>每個活動各自算，目前都暫用<Term k="break_even" value={cap.break_even}>打平線</Term> {formatAmount(cap.value)}</>
      : <>每個活動各有<Term k="cap">上限</Term>，目前都是 {formatAmount(cap.value)}</>;
  }
  const live = (home.campaigns ?? []).filter((c: HomeCampaign) => c.draft === null);
  if (live.length && live.every((c) => c.cap === null)) return "還沒設上限";
  return <>每個活動的<Term k="cap">上限</Term>不一樣</>;
}

type Props = {
  brandId: string;
  state: { status: "loading" } | { status: "error" } | { status: "ready"; home: HomeOverview };
  onRetry: () => void;
  /** Open `scale_budget` row's own link (prototype 「看加預算建議 →」); null hides it. */
  scaleHref: string | null;
  /** After the budget editor closes the overview is read again (the pace uses the saved total). */
  onBudgetClosed: () => void;
  /** F46-I09: arrived through a 「設定／提高 N 月月預算」 link — the adjust area opens on load, scrolls into view and
   * the monthly-budget form starts in edit mode. */
  openBudget?: boolean;
};

export function MonthMoney({ brandId, state, onRetry, scaleHref, onBudgetClosed, openBudget = false }: Props) {
  const [adjusting, setAdjusting] = useState(openBudget);
  // Only the first opening came from the link; a later 調整 opens the panel as before.
  const [linked, setLinked] = useState(openBudget);
  const month = state.status === "ready" ? state.home.month : null;
  const adjustRef = useRef<HTMLDivElement>(null);
  const scrolled = useRef(false);
  useEffect(() => {
    if (!linked || scrolled.current || !adjusting || !month) return;
    scrolled.current = true;
    adjustRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  }, [linked, adjusting, month]);

  return (
    <>
      <section aria-label="這個月的錢" className="surface grid grid-cols-1 items-center gap-6 px-7 py-6 min-[1180px]:grid-cols-[380px_minmax(0,1fr)] min-[1180px]:gap-9">
        {state.status === "loading" && (
          <>
            <div className="flex flex-col gap-3"><Skeleton className="h-5 w-40" /><Skeleton className="h-10 w-56" /><Skeleton className="h-24 w-full" /></div>
            <Skeleton className="h-56 w-full" />
          </>
        )}
        {state.status === "error" && (
          <div className="col-span-full flex flex-wrap items-center gap-3">
            <p role="alert" className="text-sm text-muted-foreground">這個月的花費與預算暫時讀取不到・已保存的資料都還在</p>
            <Button variant="outline" size="sm" onClick={onRetry}>重新讀取</Button>
          </div>
        )}
        {state.status === "ready" && (
          <>
            <MoneyColumn home={state.home} />
            <PaceColumn home={state.home} scaleHref={scaleHref} onAdjust={() => setAdjusting(true)} />
          </>
        )}
      </section>
      {adjusting && month && (
        <div ref={adjustRef} className="flex scroll-mt-4 flex-col gap-2">
          <Button variant="ghost" size="sm" className="self-start" onClick={() => { setAdjusting(false); setLinked(false); onBudgetClosed(); }}>
            ← 收起
          </Button>
          <MonthlyBudgetPanel brandId={brandId} month={month} compact startEditing={linked} onSaved={onRetry} />
        </div>
      )}
    </>
  );
}

function MoneyColumn({ home }: { home: HomeOverview }) {
  const money = home.money;
  const prefix = currencyPrefix(home.currency);
  const prevMonth = ((monthNumber(home.month) + 10) % 12) + 1;
  const cpp = money?.cost_per_purchase ?? null;
  const cap = money?.cap ?? null;
  const prev = money?.previous_same_period ?? null;

  const earn = money?.earn ?? null;
  const rounded = earn === null ? null : Math.round(earn / 1000) * 1000;
  const gain = rounded === null || rounded >= 0;
  const missing = (money?.earn_missing ?? []).map((m) => EARN_MISSING[m]).filter(Boolean);

  const purchases = money?.purchases ?? null;
  const dr = purchases !== null && prev?.purchases != null ? purchases - prev.purchases : null;
  const dc = cpp !== null && prev?.cost_per_purchase ? Math.round((1 - cpp / prev.cost_per_purchase) * 100) : null;

  return (
    <div className="flex min-w-0 flex-col gap-[18px]">
      <div className="flex flex-col gap-1">
        {rounded === null ? (
          <>
            <span className="text-sm font-semibold text-muted-foreground">扣掉廣告費，這個月估計多賺</span>
            <span className="text-xl font-medium text-muted-foreground/80">
              {money === null ? "暫時讀取不到" : `算不出來・${missing.length ? missing.join("、") : "資料不完整"}`}
            </span>
          </>
        ) : (
          <>
            <span className={cn("text-[13px] font-semibold", gain ? "text-success" : "text-danger")}>
              扣掉廣告費，這個月估計{gain ? "多賺" : "少賺"}
            </span>
            <span className={cn("numeric text-4xl leading-tight font-semibold tracking-tight", gain ? "text-success" : "text-danger")}>
              約 {prefix}{formatAmount(Math.abs(rounded))}
            </span>
          </>
        )}
      </div>

      <div>
        <div className="text-[13px] text-muted-foreground">每賣出一筆，廣告花</div>
        <div className="flex flex-wrap items-baseline gap-3">
          <span className="numeric text-[30px] font-semibold tracking-tight">
            {cpp !== null
              ? `${prefix}${wholeYuan(cpp)}`
              : <span className="text-xl font-medium text-muted-foreground/80">{purchases === 0 ? "還沒有購買" : "算不出來"}</span>}
          </span>
          <span className="text-sm text-muted-foreground">{capText(home)}</span>
          <MoneyTag cost={cpp} breakEven={cap?.break_even ?? null} />
        </div>
        <MoneyMeter value={cpp} cap={cap && cap.basis ? { value: cap.value, basis: cap.basis } : null} max={Math.max(600, (cpp ?? 0) * 1.3)} size="lg"
          capLabel={cap?.basis === "break_even" ? "各活動打平線" : "各活動上限"} />
      </div>

      <div className="grid grid-cols-2 gap-3 border-t border-border pt-4">
        <div>
          <div className="text-sm text-muted-foreground">購買</div>
          <div className="numeric text-xl font-semibold">{purchases === null ? "—" : `${formatAmount(purchases)} 筆`}</div>
          <div className={cn("text-sm", dr === null ? "text-muted-foreground" : dr >= 0 ? "text-success" : "text-danger")}>
            {dr === null ? `${prevMonth} 月同期沒有可比資料` : `比 ${prevMonth} 月同期${dr >= 0 ? "多" : "少"} ${formatAmount(Math.abs(dr))} 筆`}
          </div>
        </div>
        <div>
          <div className="text-sm text-muted-foreground">每賣一筆</div>
          <div className="numeric text-xl font-semibold">{dc === null ? "—" : `${dc >= 0 ? "便宜" : "貴"} ${Math.abs(dc)}%`}</div>
          <div className={cn("text-sm", dc === null || dc >= 0 ? "text-success" : "text-danger", prev?.cost_per_purchase == null && "text-muted-foreground")}>
            {prev?.cost_per_purchase != null ? `${prevMonth} 月同期 ${wholeYuan(prev.cost_per_purchase)}` : `${prevMonth} 月同期沒有可比資料`}
          </div>
        </div>
      </div>
    </div>
  );
}

function PaceColumn({ home, scaleHref, onAdjust }: { home: HomeOverview; scaleHref: string | null; onAdjust: () => void }) {
  const pace = home.pace;
  const daily = (pace?.daily ?? []).flatMap((d) => (d.cumulative === null ? [] : [{ day: Number(d.day.slice(8, 10)), cumulative: d.cumulative }]));
  const budget = pace?.budget_amount ?? null;
  const projected = pace?.projected_month_end ?? null;
  const available = pace?.available ?? null;
  const pacing = budget !== null && projected !== null ? (projected < budget ? "，照現在速度月底會用不完" : "，照現在速度月底會超出") : "";
  return (
    <div className="min-w-0">
      {pace !== null && (
        <PaceChart
          month={monthNumber(home.month)}
          dayOfMonth={home.day_of_month}
          daysInMonth={home.days_in_month}
          budget={budget}
          spent={home.spent}
          daily={daily}
          projected={projected}
        />
      )}
      <div className="mt-1.5 flex flex-wrap items-center gap-3 rounded-[10px] bg-accent px-3.5 py-3">
        <span className="min-w-0 flex-1 text-sm">
          {pace === null
            ? <span role="alert">預算進度暫時讀取不到</span>
            : budget === null
            ? "還沒設這個月的預算"
            : available === null
              ? <>還能花 <b className="numeric">尚待確認</b>{pacing}</>
              : <>還能花 <b className="numeric">{formatAmount(available)} 元</b>{pacing}</>}
        </span>
        {scaleHref && (
          <Button asChild variant="link" className="h-auto p-0 font-semibold">
            <Link to={scaleHref}>看加預算建議 →</Link>
          </Button>
        )}
        <Button variant="link" className="h-auto p-0 font-semibold" onClick={onAdjust}>調整</Button>
      </div>
    </div>
  );
}
