import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { PageHeader } from "@/components/layout/PageHeader";
import { Skeleton } from "@/components/layout/Skeleton";
import { Button } from "@/components/layout/ui/button";
import { getHomeOverview, type HomeOverview } from "@/lib/adsHomeApi";
import { dismissSuggestion, getMonthSummary, type MonthSuggestion, type MonthSummary } from "@/lib/adsMonthApi";
import { useApiRead } from "@/lib/useApiRead";
import { cn } from "@/lib/utils";
import { ActionBar, CampaignChip, Chip, ReadFailed, formatAmount, type ObjectiveKey } from "../patterns";
import { currentBudgetMonth } from "../MonthlyBudgetPanel";
import { useOrgClock } from "@/lib/orgClock";
import { GradeBuckets, GradeSplit, MissingNote } from "./MonthGrades";
import { MonthFootnote, RejectedCard } from "./RejectedCards";
import { downloadMonthCsv, monthNum, shiftMonth, weekBars, type WeekBar } from "./monthCsv";

/** 每月回顧 (F29-I15, prototype v10 `month()`, hashes `#/month` and `#/month/8`): campaigns keep running; this page
 * only settles the books for one calendar month, graded by the one cap ruler (Feature F29 Contract C). Two reads,
 * each failing on its own: `GET …/month-summary?month=` (grades, rejected cleanups, suggestions, closed count) and
 * `GET …/home?month=` (the weekly pace and the same-days-last-month trend). The month is `?month=YYYY-MM` (this
 * month or the previous one). Nothing here writes to an ad platform; 先不要 on a suggestion only hides it for the
 * month. The current month shows its grade split, next month's suggestions, the worsened rejected cleanups and
 * the footnote; a past month shows its weekly spend, buckets and closed count (the prototype's 8 月). */

const HATCH = "bg-[repeating-linear-gradient(45deg,var(--color-border)_0_4px,var(--color-background)_4px_8px)]";
const CHART_H = 150;

function WeeklySpend({ home }: { home: HomeOverview }) {
  const pace = home.pace;
  const budget = pace?.budget_amount ?? null;
  const bars: WeekBar[] = pace ? weekBars(home.month, home.days_in_month, pace.daily, budget) : [];
  const top = Math.max(1, ...bars.flatMap((w) => [w.spend ?? 0, w.pace ?? 0])) * 1.1;
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
              : <span><i aria-hidden="true" className="mr-[5px] inline-block w-3.5 border-t-2 border-dashed border-chart-rest align-middle" />月預算 {formatAmount(budget)} 的步調</span>}
          </div>
          <b className="numeric font-semibold">已花 {formatAmount(home.spent) ?? "未知"}</b>
        </div>
      </div>
      {pace === null ? <p className="text-sm text-muted-foreground">這個月的每日花費讀不到，其他區塊照常。</p> : (
        <>
          <div className="relative grid h-[190px] items-end gap-[18px] border-b border-border px-1.5 max-md:gap-1.5" style={cols}>
            {bars.map((w) => (
              <div key={w.label} data-week={w.state} className="relative flex h-full flex-col items-center justify-end">
                {w.state === "known" ? (
                  <>
                    <span className="numeric mb-1 text-xs font-semibold">{formatAmount(Math.round(w.spend as number))}</span>
                    <div className="w-[56%] max-w-16 rounded-t-md bg-primary" style={{ height: px(w.spend as number) }} />
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
                    className="absolute inset-x-[10%] border-t-2 border-dashed border-chart-rest" style={{ bottom: px(w.pace) }}
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

function ClosedCard({ summary }: { summary: MonthSummary }) {
  const known = summary.closed_this_month !== null;
  const since = summary.closed_tracking_since.slice(0, 10).split("-").map(Number).join("/");
  return (
    <section aria-label="這個月關掉的" className="flex flex-wrap items-center gap-3.5 rounded-xl border border-border bg-muted px-[22px] py-5">
      <span aria-hidden="true" className="grid size-10 place-items-center rounded-[10px] bg-card">✂</span>
      <div className="min-w-0 flex-1">
        <b className="text-base font-semibold">{known ? `這個月關掉 ${summary.closed_this_month} 則` : "這個月關掉幾則還沒有紀錄"}</b>
        <div className="text-[13px] text-muted-foreground">{known ? "原因與當時成效都留著" : `關閉時間從 ${since} 起記錄`}</div>
      </div>
      {known && <Chip tone="neutral">紀錄保留</Chip>}
    </section>
  );
}

function SuggestionCard({ brandId, month, suggestion, onDismissed }: {
  brandId: string; month: string; suggestion: MonthSuggestion; onDismissed: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const skip = () => {
    setBusy(true);
    setError("");
    dismissSuggestion(brandId, month, suggestion.key)
      .then(onDismissed)
      .catch((err: unknown) => {
        setBusy(false);
        setError(err instanceof Error ? err.message : "先不要沒有存到，請稍後再試。");
      });
  };
  // F46: a next_plan card opens the create page for the next period; every other kind opens its proposal.
  const actionLabel = suggestion.kind === "next_plan" ? "用這些學習排下一期 →" : "看提議（核准或拒絕）→";
  return (
    <section aria-label={suggestion.title} data-kind={suggestion.kind} className="surface flex flex-col px-[22px] py-5">
      <CampaignChip objective={suggestion.campaign_objective ?? "other"} name={suggestion.campaign_name} suffix={suggestion.objective} />
      <b className="mt-2.5 mb-0.5 block text-[15px] font-semibold [overflow-wrap:anywhere]">{suggestion.title}</b>
      <div className="mb-3.5 text-[13px] text-muted-foreground">{suggestion.why}</div>
      {error && <p role="alert" className="mb-2 text-xs text-danger">{error}</p>}
      <div className="flex flex-wrap gap-2">
        {suggestion.action_url
          ? <Button size="sm" variant="outline" asChild><Link to={suggestion.action_url}>{actionLabel}</Link></Button>
          : <Button size="sm" variant="outline" disabled>{actionLabel}</Button>}
        <Button size="sm" variant="ghost" disabled={busy} onClick={skip}>先不要</Button>
      </div>
    </section>
  );
}

/** 「比 8 月同期（只當參考，不影響判斷）：購買多 40 筆・每筆便宜 37%」 from the home overview's money block. */
function trendText(home: HomeOverview, prevMonth: number): string | null {
  const money = home.money;
  if (!money) return null;
  const head = `比 ${prevMonth} 月同期（只當參考，不影響判斷）：`;
  const prev = money.previous_same_period;
  if (!prev || money.purchases === null || prev.purchases === null) return `${head}沒有可比的購買數`;
  const dr = money.purchases - prev.purchases;
  const dc = money.cost_per_purchase !== null && prev.cost_per_purchase
    ? Math.round((1 - money.cost_per_purchase / prev.cost_per_purchase) * 100) : null;
  return `${head}購買${dr >= 0 ? "多" : "少"} ${formatAmount(Math.abs(dr))} 筆${dc === null ? "" : `・每筆${dc >= 0 ? "便宜" : "貴"} ${Math.abs(dc)}%`}`;
}

function objectiveOf(summary: MonthSummary, campaignId: string): ObjectiveKey {
  return summary.campaigns.find((c) => c.campaign_id === campaignId)?.campaign_objective ?? "other";
}

/** The next-month suggestions and the worsened rejected cleanups (current month only). 先不要 dismisses a card for
 * the month on the server; a rejected card's dismissal is its campaign's `cleanup:<id>` key, which also retires that
 * campaign's cleanup suggestion for the month (one store), so both leave the screen together. */
function Suggestions({ brandId, month, summary }: { brandId: string; month: string; summary: MonthSummary }) {
  const [hidden, setHidden] = useState<Set<string>>(() => new Set());
  const hide = (key: string) => setHidden((prev) => new Set(prev).add(key));
  const suggestions = summary.suggestions.filter((s) => !hidden.has(`s:${s.key}`));
  const worse = summary.rejected.worse.filter((r) => !hidden.has(`s:cleanup:${r.campaign_id}`));
  return (
    <section aria-label={`${monthNum(shiftMonth(month, 1))} 月建議`}>
      <h2 className="mt-2 mb-2.5 text-[15px] font-semibold">{monthNum(shiftMonth(month, 1))} 月建議</h2>
      {suggestions.length + worse.length === 0
        ? <p className="text-sm text-muted-foreground">這個月沒有要給下個月的建議。</p>
        : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            {suggestions.map((s) => (
              <SuggestionCard key={s.key} brandId={brandId} month={month} suggestion={s} onDismissed={() => hide(`s:${s.key}`)} />
            ))}
            {worse.map((card) => (
              <RejectedCard
                key={card.change_set_id} brandId={brandId} month={month} card={card}
                objective={objectiveOf(summary, card.campaign_id)} onDismissed={() => hide(`s:cleanup:${card.campaign_id}`)}
              />
            ))}
          </div>
        )}
    </section>
  );
}

export function MonthReviewPage({ brandId }: { brandId: string }) {
  const homeHref = `/brands/${brandId}/ads`;
  const { timezone } = useOrgClock();
  const thisMonth = useMemo(() => currentBudgetMonth(timezone), [timezone]);
  const lastMonth = shiftMonth(thisMonth, -1);
  const [params, setParams] = useSearchParams();
  const month = params.get("month") === lastMonth ? lastMonth : thisMonth;
  const current = month === thisMonth;

  const summary = useApiRead((signal) => getMonthSummary(brandId, month, signal), [brandId, month]);
  const home = useApiRead((signal) => getHomeOverview(brandId, month, signal), [brandId, month]);
  const view = summary.data;
  const homeView = home.data;

  const pick = (value: string) => setParams(value === thisMonth ? {} : { month: value });
  const monthButton = (value: string) => (
    <Button key={value} size="sm" variant={value === month ? "default" : "outline"} aria-pressed={value === month} onClick={() => pick(value)}>
      {monthNum(value)} 月
    </Button>
  );

  return (
    <div className="flex min-h-[calc(100dvh-108px)] flex-col xl:min-h-[calc(100dvh-120px)]">
      <div className="flex max-w-[1260px] flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "每月回顧" }]} />
        <PageHeader
          title={`${monthNum(month)} 月回顧`}
          description="活動照常投放，這裡只整理帳"
          actions={
            <>
              <Button size="sm" variant="outline" disabled={!view} onClick={() => view && downloadMonthCsv(month, view.grades.rows)}>下載 CSV</Button>
              <div role="group" aria-label="月份" className="flex gap-1.5">{[lastMonth, thisMonth].map(monthButton)}</div>
            </>
          }
        />

        {home.status === "error"
          ? <ReadFailed what={`每週花費讀不到；廣告照常投放，其他區塊照常顯示（${home.error}）`} onRetry={home.reload} />
          : homeView ? <WeeklySpend home={homeView} /> : <div className="surface px-[22px] py-5"><Skeleton className="h-[230px] w-full" /></div>}

        {summary.status === "error" ? (
          <ReadFailed what={`這個月的分級與建議讀不到；廣告照常投放，沒有東西被改動（${summary.error}）`} onRetry={summary.reload} />
        ) : !view ? (
          <div className="flex flex-col gap-4" aria-busy="true">
            <Skeleton className="h-36 w-full" />
            <Skeleton className="h-40 w-full" />
          </div>
        ) : (
          <>
            {current ? <GradeSplit month={monthNum(month)} grades={view.grades} /> : <MissingNote grades={view.grades} />}
            <GradeBuckets grades={view.grades} withAmounts={current} />
            <ClosedCard summary={view} />
            {current && <Suggestions brandId={brandId} month={month} summary={view} />}
            {current && (
              <MonthFootnote
                sameCount={view.rejected.same_count}
                trend={homeView ? trendText(homeView, monthNum(lastMonth)) : null}
              />
            )}
          </>
        )}
      </div>
      <div className="flex-1" />
      <ActionBar back={{ label: "投放中心", to: homeHref }} />
    </div>
  );
}
