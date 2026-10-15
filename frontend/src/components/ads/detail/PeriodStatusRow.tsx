import { Figure } from "@/components/layout/Figure";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/layout/ui/button";
import { getPerformance, type CampaignDetail, type PeriodGrade, type CampaignPerformance, type ImportedCampaignPerformance } from "@/lib/adsApi";
import type { SyncOutcome } from "@/lib/adsExternalApi";
import { daysBetween, formatInstant, useOrgClock } from "@/lib/orgClock";
import { formatMoney } from "@/lib/format";
import { useApiRead } from "@/lib/useApiRead";
import { getCoordinateLearnings } from "@/lib/adsLearningsApi";
import { CloseCampaignDialog, LearningExits, coveredRange, shortDay } from "../CloseCampaignDialog";
import { nativePerformance, nativeMetricScopes } from "../nativePerformance";
import { Chip, GradeTermChip, ReadFailed, formatAmount } from "../patterns";
import { perSaleAmount } from "../patterns/csv";

/** F40-I06 (drill-7 #9 #12, prototype `#/perf` `statusCard`): the 「這期狀態列」 on top of the 成效分頁 for a
 * live／ended／closed campaign. Five cells use the served completed period/currency: 期間, 花費
 * 整期合計, 購買 平台回報, 每賣一筆 with the period's one-ruler grade (`totals.grade`, the backend's answer) beside
 * 對上限 N, ROAS 營收 ÷ 花費 — the two actions 重新讀取平台／結案這一期 (the same `CloseCampaignDialog` the folded old
 * panel opens), the data-status chip and the 整期 vs 每月回顧 caption. Numbers: `getPerformance` totals for an
 * internal campaign; an imported one reads the same route's scoped native view, no grade and no
 * close (`capabilities.unavailable.close`). A closed campaign keeps its numbers and loses the buttons (chip 已結案).
 * F49 Contract L: 結案這一期 shows only when the served `lifecycle.can_close` (never on a draft or an imported
 * campaign); the queue's closeout row links here with `?close=1`, which opens the close dialog once on load and is
 * dropped from the URL when the dialog closes. F49 Contract O: the workspace's last platform read prints its served
 * outcome sentence beside 重新讀取平台 (`syncNote`), so a half-failed read never ends silently. */

const md = (iso: string) => `${iso.slice(5, 7)}/${iso.slice(8, 10)}`;

/** Calendar days `start … min(end, today)` inclusive (`app/ads/outcome.py::_window_days`); null without a start. */
export function periodDays(start: string | null, end: string | null, today: string): number | null {
  if (!start) return null;
  const last = end && end < today ? end : today;
  if (last < start) return 0;
  return daysBetween(start, last);
}

/** The warning chip's day list (prototype 「10/01、10/02 沒讀到，不算 0」); a long gap prints as a range. */
export function missingDaysChip(days: string[]): string {
  const sorted = [...days].sort();
  const which = sorted.length <= 3 ? sorted.map(shortDay).join("、") : `${shortDay(sorted[0])}–${shortDay(sorted[sorted.length - 1])} 間 ${sorted.length} 天`;
  return `${which} 沒讀到，不算 0`;
}

/** The newest platform read: `external_view.sync.*.last_success_at` when the campaign carries the view, else the
 * caller's campaign-level `data.sync.last_success_at` (the same newest-section value, `adsApi.ts`). */
export function latestReadAt(c: CampaignDetail, fallback: string | null): string | null {
  const stamps = Object.values(c.external_view?.sync ?? {}).map((s) => s.last_success_at).filter((s): s is string => Boolean(s));
  if (stamps.length) return stamps.sort().at(-1) as string;
  return fallback;
}

function Cell({ label, value, sub, size = "text-[22px]" }: { label: string; value: ReactNode; sub: ReactNode; size?: string }) {
  return (
    <div className="min-w-0 border-l border-border px-[18px] py-0.5 first:border-l-0 first:pl-0 max-md:odd:border-l-0 max-md:odd:pl-0 max-md:px-3 max-md:py-1.5">
      <span className="block text-xs text-muted-foreground">{label}</span>
      <b className={`my-0.5 block whitespace-nowrap font-semibold tracking-[-0.02em] ${size}`}>{value}</b>
      <span className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">{sub}</span>
    </div>
  );
}

/** The finished platform read the workspace prints beside 重新讀取平台 (the served outcome, never re-worded). */
export interface SyncNote { state: SyncOutcome["state"] | "error"; text: string }

/** A read that did not get everything is a warning; a failed one (or an unreadable outcome) is an error. */
export function syncNoteTone(note: SyncNote): string {
  return note.state === "failed" || note.state === "error" ? "text-danger" : note.state === "partial" ? "text-warning" : "text-muted-foreground";
}

export function PeriodStatusRow({ brandId, campaign: c, lastSuccessAt = null, onCampaignChange, onSync, syncing = false, syncError = "", syncNote = null, readGeneration = 0 }: {
  brandId: string;
  campaign: CampaignDetail;
  /** The triage read's `data.sync.last_success_at` (the 「最新 …」 fallback for an internal campaign). */
  lastSuccessAt?: string | null;
  onCampaignChange: (campaign: CampaignDetail) => void;
  onSync?: () => void;
  syncing?: boolean;
  syncError?: string;
  /** F49 Contract O: the outcome of the workspace's last platform read, null before one finished. */
  syncNote?: SyncNote | null;
  readGeneration?: number;
}) {
  const { today, timezone } = useOrgClock();
  const imported = c.origin === "imported";
  const closed = c.lifecycle?.state === "closed";
  const canClose = c.lifecycle?.can_close === true;
  const perf = useApiRead<CampaignPerformance | ImportedCampaignPerformance>(
    () => imported ? getPerformance(brandId, c.id, true) : getPerformance(brandId, c.id),
    [brandId, c.id, imported],
  );
  const [closeOpen, setCloseOpen] = useState(false);
  // `?close=1` (the closeout row's link): open the dialog once; the param goes when the dialog closes, or at once when
  // this campaign cannot be closed (a draft, imported or already closed).
  const [searchParams, setSearchParams] = useSearchParams();
  const askedClose = searchParams.get("close") === "1";
  useEffect(() => {
    if (!askedClose) return;
    if (canClose) setCloseOpen(true);
    else dropCloseParam();
  }, [askedClose, canClose]); // once per arrival of the param
  function dropCloseParam() {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete("close");
      return next;
    }, { replace: true });
  }
  function closeDialog() {
    setCloseOpen(false);
    if (askedClose) dropCloseParam();
  }
  // F46: a closed internal campaign's row links to what it taught and to the next period; the next-period href is
  // the view's own (`next.new_campaign_href`), the plain create page while unread or when the read fails.
  const learned = useApiRead(
    (signal) => (closed && !imported ? getCoordinateLearnings(brandId, { campaignId: c.id }, signal) : Promise.resolve(null)),
    [brandId, c.id, closed, imported],
  );

  // The workspace supplies a terminal generation; posting false alone proves no completed read.
  const previousRead = useRef(readGeneration);
  const reload = perf.reload;
  useEffect(() => {
    if (previousRead.current !== readGeneration) reload();
    previousRead.current = readGeneration;
  }, [readGeneration, reload]);

  const data = perf.status === "ready" ? perf.data : null;
  const internal = data && "totals" in data ? data : null;
  const nativeView = data && "external_view" in data ? data.external_view : null;
  const native = nativeView ? nativePerformance(nativeView) : null;
  const totals = imported ? native?.totals : internal?.totals;
  const nativeScope = nativeMetricScopes(nativeView)[0];
  const result = internal?.result_view ?? nativeView?.result_views?.find(view => view.scope_key === nativeScope?.key);
  const grade: PeriodGrade | null = internal?.totals.grade ?? null;
  const coverage = internal?.coverage;
  const scope = internal?.scope ?? native?.scope;
  const currency = result ? result.currency : imported ? nativeMetricScopes(nativeView)[0]?.currency ?? null : scope?.currency;
  const missingDays = coverage?.missing_days ?? [];
  const covered = coverage?.start && coverage.end ? coveredRange(coverage.start, coverage.end, missingDays) : null;
  const latest = latestReadAt(c, lastSuccessAt);
  const days = scope?.days ?? null;
  const cap = result ? result.target.value : c.cap.value;
  const capCurrency = result?.comparison?.currency ?? internal?.cap_comparison?.currency ?? "幣別未知";

  const dash = perf.status === "loading" ? "…" : "—";
  const unit = currency ?? "幣別未知";
  const spend = result ? result.spend === null ? "未知" : formatMoney(result.spend, unit)
    : totals ? totals.spend === null ? "未知" : formatMoney(totals.spend, unit) : dash;
  const purchases = result ? result.count === null ? "未知" : `${formatAmount(result.count)} 次`
    : totals ? (totals.purchases === null ? "未追蹤" : `${formatAmount(totals.purchases)} 筆`) : dash;
  const cpa = result ? result.cost_per_result === null ? "算不出來" : `${perSaleAmount(result.cost_per_result)} ${unit}`
    : totals ? (totals.cpa === null ? "算不出來" : `${perSaleAmount(totals.cpa)} ${unit}`) : dash;

  const closeCaption = imported
    ? (c.capabilities?.unavailable.close ?? "既有平台活動不使用內部結案。")
    : missingDays.length ? "會先問要不要重新讀取，再結案" : "結案後這期成績寫進筆記本，下一期照它規劃";

  return (
    <section className="surface px-[22px] py-5" aria-label="這期狀態列" data-testid="period-status-row">
      <div className="mb-3.5 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-[15px] font-semibold">這期狀態列</h2>
        <span className="text-[12.5px] text-muted-foreground">
          {c.start_date ? `${md(c.start_date)} 開始` : "還沒設開始日"}・{c.end_date ? `${md(c.end_date)} 結束` : "還沒設結束日"}・今天 {md(today)}
        </span>
      </div>
      <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-5 max-xl:grid-cols-1">
        <div className="grid grid-cols-5 max-md:grid-cols-2">
          <Cell label="期間" size="text-lg"
            value={scope?.start && scope.end ? `${md(scope.start)}～${md(scope.end)}` : "未核實"}
            sub={days === null ? "成效期間未核實" : `${days} 天`} />
          <Cell label="花費" value={spend} sub={imported ? "查詢期間合計" : "整期合計"} />
          <Cell label={result ? result.result_label : "購買"} value={purchases} sub="平台回報" />
          <Cell label={result ? `每次${result.result_label}成本` : "每賣一筆"} value={cpa} sub={
            <>
              {(grade || imported) && <GradeTermChip grade={grade?.grade ?? null} label={result && grade?.grade === "wasted" ? "零成果、支出偏高" : grade?.label} />}
              {cap !== null ? `對上限 ${formatAmount(cap)} ${capCurrency}` : "沒設上限"}
            </>
          } />
          <Cell label="ROAS" size="text-base" value={<Figure basis="roas_all_spend" value={totals?.roas_all_spend} alt={{basis: "roas_tracked_spend", value: totals?.roas_tracked_spend ?? null}} />} sub={result ? "次要資料：平台營收／花費" : ""} />
        </div>
        {closed ? (
          <div className="flex flex-wrap items-center justify-end gap-2" data-testid="period-closed-exits">
            <Chip data-state="closed">已結案</Chip>
            {!imported && <LearningExits brandId={brandId} campaignId={c.id} view={learned.data} />}
          </div>
        ) : (
          <div className="flex flex-col items-end gap-2">
            <div className="flex items-center gap-2">
              <Button type="button" variant="outline" onClick={() => onSync?.()} busy={syncing} disabledReason={!onSync ? "目前無法重新讀取平台" : undefined}>
                <RefreshCw size={14} className={syncing ? "animate-spin" : "hidden"} />
                {syncing ? "讀取中…" : "重新讀取平台"}
              </Button>
              {canClose && <Button type="button" onClick={() => setCloseOpen(true)}>結案這一期 →</Button>}
            </div>
            {syncNote && !syncing && (
              <small role="status" data-state={syncNote.state} className={`max-w-[26rem] text-right text-[11.5px] ${syncNoteTone(syncNote)}`}>{syncNote.text}</small>
            )}
            <small className="text-[11.5px] text-muted-foreground">{closeCaption}</small>
          </div>
        )}
      </div>
      <div className="mt-3.5 flex flex-wrap items-center gap-2.5" data-testid="period-data-status">
        {perf.status === "error" && <ReadFailed what={`整期合計讀不到：${perf.error}`} onRetry={perf.reload} />}
        {coverage?.never_synced && <Chip tone="warn" data-state="never">還沒讀過平台資料</Chip>}
        {!coverage?.never_synced && missingDays.length > 0 && <Chip tone="warn" data-state="partial">{missingDaysChip(missingDays)}</Chip>}
        {!coverage?.never_synced && missingDays.length === 0 && covered && (
          <Chip tone="ok" data-state="ready">平台已讀到 {shortDay(covered.first)}～{shortDay(covered.last)}</Chip>
        )}
        <span className="text-[12.5px] text-muted-foreground">
          {missingDays.length > 0 && covered && `平台已讀到 ${shortDay(covered.first)}～${shortDay(covered.last)}・`}
          {latest ? `最新 ${formatInstant(latest, timezone, "md_hm")}` : "還沒有讀取紀錄"}
        </span>
      </div>
      {scope?.caption && <p className="mt-2 text-[11.5px] text-muted-foreground">{scope.caption}</p>}
      {scope?.reason_text && <p className="mt-2 text-[11.5px] text-warning">{scope.reason_text}</p>}
      {internal?.cap_comparison?.message && <p className="mt-2 text-[11.5px] text-warning">{internal.cap_comparison.message}</p>}
      {imported && result?.comparison?.message && <p className="mt-2 text-[11.5px] text-warning">{result.comparison.message}</p>}
      {result && <p className="mt-2 text-[11.5px] text-muted-foreground">
        {result.data_state === "known_zero" ? "已追蹤零成果；支出風險另外看。"
          : result.data_state === "incomplete" ? "成果資料仍有缺漏，未知不算零；先補讀缺漏日期與核實成果定義。"
          : result.comparison_state === "incompatible" ? "成果或資料單位與上限不一致，先核實後再比對。"
          : result.comparison_state === "unconfigured" ? "上限或成果目標尚未核實，回到策略確認。"
          : "這是成本上限比較，不代表已證明有效或已付款利潤。"}
        樣本：{result.count === null ? "總成果未知" : `${formatAmount(result.count)} 次${result.result_label}`}・{result.sample.days ?? "未知"} 天。
      </p>}
      <p className="mt-2 text-[11.5px] text-muted-foreground">整期＝活動期間的合計；每月回顧只算當月天數，同一則廣告兩邊數字會不同。</p>
      {closeOpen && (
        <CloseCampaignDialog brandId={brandId} campaign={c} onClose={closeDialog}
          onCampaignChange={onCampaignChange} onSync={onSync} syncing={syncing} syncError={syncError} readGeneration={readGeneration} />
      )}
    </section>
  );
}
