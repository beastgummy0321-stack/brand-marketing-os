import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { PageHeader } from "@/components/layout/PageHeader";
import { Skeleton } from "@/components/layout/Skeleton";
import { Button } from "@/components/layout/ui/button";
import { getHomeOverview, type HomeOverview } from "@/lib/adsHomeApi";
import { dismissSuggestion, getMonthSummary, type MonthSuggestion, type MonthSummary } from "@/lib/adsMonthApi";
import { useApiRead } from "@/lib/useApiRead";
import { ActionBar, CampaignChip, Chip, ReadFailed, formatAmount, type ObjectiveKey } from "../patterns";
import { currentBudgetMonth } from "../MonthlyBudgetPanel";
import { orgDateOf, shiftMonth, useOrgClock } from "@/lib/orgClock";
import { GradeBuckets, GradeSplit, MissingNote } from "./MonthGrades";
import { WeeklySpend } from "./WeeklySpend";
import { MonthOrders } from "./MonthOrders";
import { settlePath } from "../settle/SettlePage";
import { MonthFootnote, RejectedCard } from "./RejectedCards";
import { downloadMonthCsv, monthNum, money as moneyText } from "./monthCsv";

/** 每月回顧 (F29-I15, prototype v10 `month()`, hashes `#/month` and `#/month/8`): campaigns keep running; this page
 * only settles the books for one calendar month, graded by the one cap ruler (Feature F29 Contract C). Two reads,
 * each failing on its own: `GET …/month-summary?month=` (grades, rejected cleanups, suggestions, closed count) and
 * `GET …/home?month=` (the weekly pace and the same-days-last-month trend). The month is `?month=YYYY-MM` (this
 * month or the previous one). Nothing here writes to an ad platform; 先不要 on a suggestion only hides it for the
 * month. The current month shows its grade split, next month's suggestions, the worsened rejected cleanups and
 * the footnote; a past month shows its weekly spend, buckets and closed count (the prototype's 8 月). */

function ClosedCard({ summary }: { summary: MonthSummary }) {
  const known = summary.closed_this_month !== null;
  // The tracking start is an instant: its day on the org's calendar (F50 Contract K), not the UTC date.
  const { timezone } = useOrgClock();
  const since = (orgDateOf(summary.closed_tracking_since, timezone) ?? "").split("-").map(Number).join("/");
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
  // A current-month source is incomplete; next-period confirmation starts from its completed settle.
  const next = suggestion.kind === "next_plan";
  const actionLabel = next ? "來源月份尚未完成" : "看提議（核准或拒絕）→";
  return (
    <section aria-label={suggestion.title} data-kind={suggestion.kind} className="surface flex min-w-0 flex-col px-[22px] py-5">
      <CampaignChip objective={suggestion.campaign_objective ?? "other"} name={suggestion.campaign_name} suffix={suggestion.objective} />
      <b className="mt-2.5 mb-0.5 block text-[15px] font-semibold [overflow-wrap:anywhere]">{suggestion.title}</b>
      <div className="mb-3.5 text-[13px] text-muted-foreground [overflow-wrap:anywhere]">{suggestion.why}</div>
      {error && <p role="alert" className="mb-2 text-xs text-danger">{error}</p>}
      <div className="flex flex-wrap gap-2">
        {next ? <Button size="sm" variant="outline" disabledReason="本月尚未完成，完成後從本月結算選擇下一期來源。">{actionLabel}</Button> : suggestion.action_url
          ? <Button size="sm" variant="outline" asChild><Link to={suggestion.action_url}>{actionLabel}</Link></Button>
          : <Button size="sm" variant="outline" disabledReason="提議連結目前無法取得，請重新整理再試。">{actionLabel}</Button>}
        <Button size="sm" variant="ghost" busy={busy} onClick={skip}>先不要</Button>
      </div>
    </section>
  );
}

/** Cost trends require the producer qualification and the same known unit. */
function trendText(home: HomeOverview, prevMonth: number): string | null {
  const current = home.money;
  const prev = current?.previous_same_period;
  if (!current || !prev) return null;
  const head = `比 ${prevMonth} 月同期（只當參考，不影響判斷）：`;
  const comparable = !!home.currency && home.currency === prev.currency && prev.cost_comparison?.reason === null;
  const dr = current.purchases !== null && prev.purchases !== null ? current.purchases - prev.purchases : null;
  const count = dr === null ? "平台購買數尚無可比資料" : `平台購買${dr >= 0 ? "多" : "少"} ${formatAmount(Math.abs(dr))} 筆`;
  const dc = comparable && current.cost_per_purchase !== null && current.cost_per_purchase >= 0
    && prev.cost_per_purchase !== null && prev.cost_per_purchase > 0
    ? Math.round((1 - current.cost_per_purchase / prev.cost_per_purchase) * 100) : null;
  const ratio = dc === null ? "" : `・每筆${dc >= 0 ? "便宜" : "貴"} ${Math.abs(dc)}%`;
  return `${head}${count}${ratio}・前期每筆成本 ${moneyText(prev.cost_per_purchase, prev.currency)}，本期 ${moneyText(current.cost_per_purchase, home.currency)}${comparable ? "" : "（幣別無法比較）"}`;
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
    <section aria-label={`依 ${monthNum(month)} 月結果，給 ${monthNum(shiftMonth(month, 1))} 月的建議`}>
      <h2 className="mt-2 mb-2.5 text-[15px] font-semibold">依 {monthNum(month)} 月結果，給 {monthNum(shiftMonth(month, 1))} 月的建議</h2>
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
          description="整理平台成本與品牌付款證據"
          actions={
            <>
              <Button size="sm" variant="outline" disabledReason={!view ? "先載入這個月的資料" : undefined} onClick={() => view && downloadMonthCsv(month, view.grades.rows)}>下載 CSV</Button>
              <div role="group" aria-label="月份" className="flex gap-1.5">{[lastMonth, thisMonth].map(monthButton)}</div>
            </>
          }
        />

        {home.status === "error"
          ? <ReadFailed what={`每週花費讀不到；其他區塊照常顯示（${home.error}）`} onRetry={home.reload} />
          : homeView ? <WeeklySpend home={homeView} /> : <div className="surface px-[22px] py-5"><Skeleton className="h-[230px] w-full" /></div>}

        {summary.status === "error" ? (
          <ReadFailed what={`這個月的分級與建議讀不到；沒有東西被改動（${summary.error}）`} onRetry={summary.reload} />
        ) : !view ? (
          <div className="flex flex-col gap-4" aria-busy="true">
            <Skeleton className="h-36 w-full" />
            <Skeleton className="h-40 w-full" />
          </div>
        ) : (
          <>
            <p className="text-xs text-muted-foreground">平台數字窗口：{view.window?.start ?? `${month}-01`}–{view.window?.end ?? "尚無完整日"}・{view.data_days ?? "未知"} 個已過完整日；不代表資料已完整讀取</p>
            <MonthOrders orders={view.orders} />
            {current ? <GradeSplit month={monthNum(month)} grades={view.grades} /> : <MissingNote grades={view.grades} />}
            <GradeBuckets grades={view.grades} withAmounts={current} />
            <ClosedCard summary={view} />
            {!current && <div className="flex justify-start"><Button asChild><Link to={settlePath(brandId, month, "result")}>回顧本期，準備下一期 →</Link></Button></div>}
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
