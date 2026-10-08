import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { Skeleton } from "@/components/layout/Skeleton";
import type { HomeCampaign, HomeEarnMissing, HomeOverview } from "@/lib/adsHomeApi";
import { MonthlyBudgetPanel } from "../MonthlyBudgetPanel";
import { perSaleAmount } from "../patterns/csv";
import { Chip, Disclosure, MoneyMeter, PaceChart, Term, formatAmount } from "../patterns";
import { cn } from "@/lib/utils";

/** Home money card (prototype v10 `homeMoney()`, `.moneyg`): collected paid orders, a folded platform-margin
 * hypothesis, purchase cost against the comparable shared cap, and the budget pace chart
 * with the 調整 entry to the existing monthly-budget editor. Every number comes from `GET …/home` (F28-I06);
 * `null` prints the unknown text, never 0. */

/** `TWD` → `NT$`; any other currency code is printed as-is; unknown currency prints the bare number. */
export function currencyPrefix(currency: string | null): string {
  if (currency === "TWD") return "NT$";
  return currency ? `${currency} ` : "";
}

/** The prototype's `yuan()`: a cost per purchase as whole yuan (「139 元」), through the one per-sale rule. */
export function wholeYuan(value: number): string {
  return `${perSaleAmount(value) ?? "—"} 元`;
}

/** `YYYY-MM` → month number; before the overview answers, the month of the org's `today` (`useOrgClock`, F50 Contract
 * K) when the caller passes it. */
export function monthNumber(month: string | null | undefined, today?: string): number {
  const source = month || today;
  return source ? Number(source.slice(5, 7)) : NaN;
}

const EARN_MISSING: Record<HomeEarnMissing, string> = {
  product_cost: "缺商品成本",
  product_price: "缺商品售價",
  shipping_cost: "運費尚未確認",
  sales_mix: "多商品的成交比例尚未確認",
  currency: "估算與花費的幣別不同或尚未確認",
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
  if (home.money?.configured_cap || live.some((c) => c.configured_cap && !c.cap)) return "已設上限，幣別尚無法比較";
  if (live.length && live.every((c) => c.cap === null)) return "還沒設上限";
  return <>每個活動的<Term k="cap">上限</Term>不一樣</>;
}

type Props = {
  brandId: string;
  state: { status: "loading" } | { status: "error"; message: string } | { status: "ready"; home: HomeOverview };
  onRetry: () => void;
  /** Open `scale_budget` row's own link (prototype 「看加預算建議 →」); null hides it. */
  scaleHref: string | null;
  /** After the budget editor closes the overview is read again (the pace uses the saved total). */
  onBudgetClosed: () => void;
  /** F46-I09: arrived through a 「設定／提高 N 月月預算」 link — the adjust area opens on load, scrolls into view and
   * the monthly-budget form starts in edit mode. */
  openBudget?: boolean;
  /** F49 Contract Q (drill-11 Q4): the approval page the budget link came from (`?return=`, already checked to be an
   * ads path of this brand). Once the editor saves or the area closes, 「← 回到剛才的核准」 leads back there. */
  returnTo?: string | null;
};

export function MonthMoney({ brandId, state, onRetry, scaleHref, onBudgetClosed, openBudget = false, returnTo = null }: Props) {
  const [adjusting, setAdjusting] = useState(openBudget);
  // Saved or closed once: the way back to the approval shows from then on.
  const [settled, setSettled] = useState(false);
  const back = returnTo && settled ? (
    <Button asChild variant="outline" size="sm" className="self-start">
      <Link to={returnTo}>← 回到剛才的核准</Link>
    </Button>
  ) : null;
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
            <div role="alert" className="min-w-0 flex-1 text-sm text-muted-foreground">
              <p>這個月的花費與預算暫時讀取不到・已保存的資料都還在</p>
              <p className="mt-1 break-words">{state.message}</p>
            </div>
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
      {adjusting && month ? (
        <div ref={adjustRef} className="flex scroll-mt-4 flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => { setAdjusting(false); setLinked(false); setSettled(true); onBudgetClosed(); }}>
              ← 收起
            </Button>
            {back}
          </div>
          <MonthlyBudgetPanel brandId={brandId} month={month} compact startEditing={linked} onSaved={() => { setSettled(true); onRetry(); }} />
        </div>
      ) : back}
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

  const earn = money?.earn_after_cost_and_ads ?? null;
  const missing = (money?.earn_missing ?? []).map((m) => EARN_MISSING[m]).filter(Boolean);

  const purchases = money?.purchases ?? null;
  const dr = purchases !== null && prev?.purchases != null ? purchases - prev.purchases : null;
  const costComparable = prev?.cost_comparison?.reason === null;
  const dc = costComparable && cpp !== null && prev?.cost_per_purchase ? Math.round((1 - cpp / prev.cost_per_purchase) * 100) : null;

  return (
    <div className="flex min-w-0 flex-col gap-[18px]">
      <PaidOrders home={home} />
      <Disclosure label="平台購買假設估算">
        <p className="text-sm">扣除假設商品成本與廣告費：<b className="numeric">
          {earn === null ? `算不出來・${missing.length ? missing.join("、") : "資料不完整"}`
            : `${prefix}${formatAmount(earn)}`}
        </b></p>
        <p className="mt-1 text-xs text-muted-foreground">平台購買數推估，不能當作已付款利潤</p>
        {(money?.estimate_basis?.assumptions ?? []).map((assumption) => <p key={assumption} className="text-xs text-muted-foreground">{assumption}</p>)}
      </Disclosure>

      <div>
        <div className="text-[13px] text-muted-foreground">每筆平台購買，廣告花</div>
        <div className="flex flex-wrap items-baseline gap-3">
          <span className="numeric text-[30px] font-semibold tracking-tight">
            {cpp !== null
              ? `${prefix}${wholeYuan(cpp)}`
              : <span className="text-xl font-medium text-muted-foreground/80">{purchases === 0 ? "還沒有購買" : "算不出來"}</span>}
          </span>
          <span className="text-sm text-muted-foreground">{capText(home)}</span>
          {cap?.break_even != null && <span className="text-xs text-muted-foreground">假設打平成本 {currencyPrefix(home.currency)}{formatAmount(cap.break_even)}</span>}
        </div>
        <MoneyMeter value={cpp} cap={cap && cap.basis ? { value: cap.value, basis: cap.basis } : null} max={cpp === null ? 600 : Math.max(600, cpp)} size="lg"
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
          <div className={cn("text-sm", dc === null ? "text-muted-foreground" : dc >= 0 ? "text-success" : "text-danger")}>
            {prev?.cost_per_purchase != null ? `${prevMonth} 月同期 ${currencyPrefix(prev.currency ?? null)}${wholeYuan(prev.cost_per_purchase)}` : `${prevMonth} 月同期沒有可比資料`}
          </div>
          {prev?.cost_per_purchase != null && !costComparable && <p className="text-xs text-muted-foreground">前期與本期成本幣別無法比較</p>}
        </div>
      </div>
    </div>
  );
}

function PaidOrders({ home }: { home: HomeOverview }) {
  const commerce = home.commerce;
  const orders = commerce?.order_summary;
  const mixed = orders ? orders.reported_currencies.length > 1 : false;
  const amount = mixed ? null : orders?.paid_net_amount ?? null;
  return <div className="flex min-w-0 flex-col gap-1">
    <span className="text-sm font-semibold text-muted-foreground">已收集的已付款訂單淨額</span>
    <span className="numeric text-4xl leading-tight font-semibold tracking-tight">
      {amount === null ? <span className="text-xl font-medium text-muted-foreground/80">{!commerce ? "目前無法確認訂單證據" : mixed ? "多幣別，無法合計" : "付款金額尚未確認"}</span>
        : `${currencyPrefix(orders?.currency ?? null)}${formatAmount(amount)}`}
    </span>
    {commerce && orders && <>
      <span className="text-sm text-muted-foreground">{orders.paid_count} 筆已付款・{orders.known_paid_net_count} 筆金額已知・{orders.refunded_count} 筆已退款</span>
      <span className="text-xs text-muted-foreground">僅計入已知金額的付款列，不代表全部收入</span>
      <span className="text-xs text-muted-foreground">{commerce.start}–{commerce.end}・品牌訂單，未歸因單一廣告</span>
      <span className="text-xs text-muted-foreground">來源幣別與覆蓋範圍尚未核實</span>
      <Disclosure label="訂單來源與狀態">
        <p className="text-sm">{orders.unpaid_count} 筆待付款・{orders.unknown_payment_count} 筆付款狀態未知</p>
        <p className="text-sm">{orders.unknown_amount_count} 筆金額未知・{orders.void_count} 筆取消或作廢</p>
        {commerce.limitations.map((limitation) => <p key={limitation} className="mt-1 text-xs text-muted-foreground">{limitation}</p>)}
      </Disclosure>
    </>}
  </div>;
}

function PaceColumn({ home, scaleHref, onAdjust }: { home: HomeOverview; scaleHref: string | null; onAdjust: () => void }) {
  const pace = home.pace;
  const daily = (pace?.daily ?? []).flatMap((d) => (d.cumulative === null ? [] : [{ day: Number(d.day.slice(8, 10)), cumulative: d.cumulative }]));
  // F47-I06: a 0 total (stored before Contract A refused it) has no planning meaning: read it as unset.
  const budget = pace?.budget_amount != null && pace.budget_amount > 0 ? pace.budget_amount : null;
  const projected = pace?.projected_month_end ?? null;
  const available = pace?.available ?? null;
  const comparable = !!pace?.budget_currency && pace.budget_comparison?.reason === null;
  const budgetPrefix = currencyPrefix(pace?.budget_currency ?? null);
  const pacing = comparable && budget !== null && projected !== null ? (projected < budget ? "，照現在速度月底會用不完" : "，照現在速度月底會超出") : "";
  return (
    <div className="min-w-0">
      {pace !== null && (comparable ? (
        <div>
        <p className="text-xs text-muted-foreground">預算與花費單位：{pace.budget_currency}</p>
        <PaceChart
          month={monthNumber(home.month)}
          dayOfMonth={home.day_of_month}
          daysInMonth={home.days_in_month}
          budget={budget}
          spent={home.spent}
          daily={daily}
          projected={projected}
          budgetToDate={pace?.budget_to_date ?? null}
        />
        </div>
      ) : (
        <div className="flex min-h-[220px] flex-col items-start justify-center gap-3">
          <b className="text-base">預算進度</b>
          <Chip>暫不比較</Chip>
          {budget !== null && <span className="numeric text-sm">已設月預算 {budgetPrefix}{formatAmount(budget)}</span>}
          <span className="text-sm text-muted-foreground">{pace.budget_comparison?.reason === "currency_mismatch" ? "月預算與廣告花費幣別不同" : "幣別尚未確認"}，暫不比較花費進度</span>
        </div>
      ))}
      <div className="mt-1.5 flex flex-wrap items-center gap-3 rounded-[10px] bg-accent px-3.5 py-3">
        <span className="min-w-0 flex-1 text-sm">
          {pace === null
            ? <span role="alert">預算進度暫時讀取不到</span>
            : budget === null
            ? "還沒設這個月的預算"
            : available === null
              ? <>還能花 <b className="numeric">尚待確認</b>{pacing}</>
              : <>預算可用餘額 <b className="numeric">{budgetPrefix}{formatAmount(available)}</b>{!pace.budget_currency && "（幣別未確認）"}{pacing}</>}
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
