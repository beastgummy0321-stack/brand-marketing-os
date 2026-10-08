import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { useApiRead } from "@/lib/useApiRead";
import { getTriage, type QueueCleanup, type QueueCleanupAd, type QueueItem, type TriageTargetView } from "@/lib/adsTriageApi";
import {
  ActionBar, CampaignChip, CapDots, Chip, FlowHeader, GradeRules, GradeTermChip, MoneyTag, PickRow, ReadFailed, ResultHero,
  TargetRuler, formatAmount, gradeWord, sampleWords, useAdsRules, type AdsRules, type FlowStep, type RulerAd, type RulerCap,
} from "../patterns";
import { proposeBudgetPath } from "./changeFlow";
import type { CleanupPick } from "./cleanupDraft";
import { Tile } from "./Tile";
import { perSaleAmount } from "../patterns/csv";

/** F28-I11: the cleanup proposal step (prototype v10 `stepProp()` for kind `clean`, hash `d/clean/prop`). The light
 * flow is 提議 → 確認 → 到平台完成 → 核對結果; this step only shows the queue row's `cleanup` payload (F28-I02) —
 * nothing is written until 核准 on the confirm step (`ConfirmPage`, lazy create unchanged). F29-I14: every proposed ad
 * is ticked; the folded 「進階：自己挑要關哪幾則」 unticks single ones (`cleanupDraft.ts::useCleanupPick`), and the
 * title, capacity dots, ruler and order list follow the ticked set. */

export function cleanupSteps(proposeHref?: string): FlowStep[] {
  return [{ label: "提議", to: proposeHref }, { label: "確認" }, { label: "到平台完成" }, { label: "核對結果" }];
}

/** The close list as served (F48 Contract R "ordering／verdict"): the backend ranks the campaign's ads with the one
 * ruler and serves `ads` (closing) and `keep` each in rank order — the screen prints `ads` then `keep` and never
 * re-sorts. */
export function servedCleanupAds(cleanup: Pick<QueueCleanup, "ads" | "keep">): QueueCleanupAd[] {
  return [...cleanup.ads, ...cleanup.keep];
}

/** The ad's grade word: the served word of its grade, 剛開始 vs 資料不足 split by the triage item's `reason_code`. */
export function cleanupWord(rules: AdsRules | null, ad: QueueCleanupAd, reasonCode?: string | null): string {
  return gradeWord(rules, ad.grade, reasonCode) ?? "";
}

/** 「4／5」: the served place in the campaign's ranking, 「—」 for an ad the ranking does not place (ungraded). */
export function placeText(ad: QueueCleanupAd): string {
  return ad.rank == null || ad.of == null ? "—" : `${ad.rank}／${ad.of}`;
}

/** The row's name block: the name, the program's reason sentence (`reason_text`, built from this ad's own grade and
 * numbers), and the rejected-before note. `withName={false}` leaves the name to the caller (the confirm card prints
 * its own, struck through when dropped). */
export function CleanupName({ ad, word, withName = true }: { ad: QueueCleanupAd; word: string; withName?: boolean }) {
  return (
    <>
      {withName && <p>{ad.name ?? "（未命名廣告）"}</p>}
      {ad.reason_text && <p data-part="reason" className="mt-0.5 text-xs font-normal text-muted-foreground">{ad.reason_text}</p>}
      <RejectedBeforeNote ad={ad} label={word} />
    </>
  );
}

/** The grade chip and, beside it, 「樣本少」 when the served sample is few (never 「還太新」). */
export function CleanupGrade({ ad, reasonCode }: { ad: QueueCleanupAd; reasonCode?: string | null }) {
  const rules = useAdsRules();
  return (
    <span className="flex flex-wrap items-center justify-end gap-1">
      <GradeTermChip grade={ad.grade} reasonCode={reasonCode} />
      {sampleWords(rules, ad).map((w) => <Chip key={w} tone="warn">{w}</Chip>)}
    </span>
  );
}

// F47-I06: a cost per sale prints through the one per-sale rule (whole yuan).
const unit = (currency: string | null | undefined) => currency === "TWD" ? "元" : currency ?? "幣別未知";
const money = (v: number | null, currency: string | null | undefined) => (perSaleAmount(v) === null ? "未知" : `${perSaleAmount(v)} ${unit(currency)}`);
const breakEvenComparable = (ad: QueueCleanupAd, currency: string | null) => Boolean(ad.currency && currency && ad.currency === currency);

/** The number cell of a row: 沒賣出 prints its result count, an ungraded ad prints its grade word (`word`, from
 * `reason_code`; not a cost yet), the rest print cost per result with its money tag against break-even (v10 `mt(a)`;
 * hidden when either number is unknown) and the served sales count. */
export function CostCell({ ad, word, withCaption = false, breakEven = null, breakEvenCurrency = null }: {
  ad: QueueCleanupAd; word: string; withCaption?: boolean; breakEven?: number | null; breakEvenCurrency?: string | null;
}): ReactNode {
  if (ad.grade === "wasted") {
    const count = ad.result_count === null ? "未知" : `${ad.result_count} 筆`;
    return <>{withCaption && <span className="block text-[11.5px] text-muted-foreground">購買</span>}<b className="text-[15px]">{count}</b></>;
  }
  if (ad.grade === "insufficient" || ad.grade === "no_target") {
    return <span className="font-medium text-muted-foreground">{word}</span>;
  }
  return (
    <>
      {withCaption && <span className="block text-[11.5px] text-muted-foreground">每賣一筆</span>}
      <b className="text-[15px]">{money(ad.cost_per_result, ad.currency)}</b>
      <MoneyTag cost={ad.cost_per_result} breakEven={breakEvenComparable(ad, breakEvenCurrency) ? breakEven : null} className="block" />
      {breakEven !== null && !breakEvenComparable(ad, breakEvenCurrency) && <span className="block text-[11.5px] text-muted-foreground">幣別不同或尚未核實，不比較打平線。</span>}
      {ad.sales != null && <span data-part="sales" className="block text-[11.5px] text-muted-foreground">成交 {ad.sales} 筆</span>}
    </>
  );
}

/** F29-I01 Contract B: an ad the user once declined to close is back only because its grade got worse — say so. */
export function RejectedBeforeNote({ ad, label }: { ad: QueueCleanupAd; label: string }) {
  if (!ad.rejected_before) return null;
  return <p className="mt-0.5 text-xs font-normal text-warning-strong">上次你拒絕時是{ad.rejected_before.grade_label}，現在變{label}</p>;
}

function capOf(target: TriageTargetView): RulerCap | null {
  return target.value === null || target.basis === null ? null : { value: target.value, basis: target.basis, currency: target.cap_unit?.currency ?? null };
}

/** 「每日 1,200 撐 6 則」: the daily budget is only on the campaign triage (`data.capacity`), read on its own so a
 * failure leaves the words without the amount, never the page blank — and says so (Contract K, `ReadFailed` + 重試).
 * 剛開始 vs 資料不足 come from the same read's `reason_code` (the cleanup payload carries `grade` only). */
function useCampaignExtras(brandId: string, campaignId: string) {
  const read = useApiRead((signal) => getTriage(brandId, campaignId, signal), [brandId, campaignId]);
  const t = read.data;
  return {
    daily: t?.data?.capacity?.daily_budget ?? null,
    reasons: new Map((t?.items ?? []).map((i) => [i.entity_id, i.reason_code])),
    failed: read.status === "error",
    retry: read.reload,
  };
}

function capacityText(cleanup: QueueCleanup, daily: number | null): string {
  if (cleanup.can_support === null) return "預算撐幾則還不知道";
  return daily === null ? `預算撐 ${cleanup.can_support} 則` : `每日 ${formatAmount(daily)} 撐 ${cleanup.can_support} 則`;
}

function shortTitle(cleanup: QueueCleanup, scale: boolean): string {
  const allOnTarget = cleanup.keep.every((ad) => ad.grade === "on_target");
  const head = allOnTarget ? "剩下的都划算，不關" : `還多 ${cleanup.short} 則放不下，其餘先不關`;
  return scale ? `${head}；改提議加預算` : head;
}

/** A pick row's numbers (v10 `.pickrow` right cell): 沒賣出 = spend and results, else cost per result + money tag. */
function pickAside(ad: QueueCleanupAd, breakEven: number | null, breakEvenCurrency: string | null): ReactNode {
  if (ad.grade === "wasted") {
    return `花 ${formatAmount(ad.spend) ?? "未知"} ${unit(ad.currency)}・${ad.result_count === null ? "未知" : `${ad.result_count} 筆`}`;
  }
  return <>每筆 {money(ad.cost_per_result, ad.currency)}<MoneyTag cost={ad.cost_per_result} breakEven={breakEvenComparable(ad, breakEvenCurrency) ? breakEven : null} plain className="block" /></>;
}

export function CleanupProposal({ brandId, campaignId, item, position, homeHref, pick }: {
  brandId: string; campaignId: string; item: QueueItem & { cleanup: QueueCleanup };
  position: { pos: number; total: number } | null; homeHref: string; pick: CleanupPick;
}) {
  const { cleanup, triage } = item;
  const extras = useCampaignExtras(brandId, campaignId);
  const rules = useAdsRules();
  // The fold opens by itself when the user comes back with a pick already made (prototype `S.open.cleanAdv`).
  const [advOpen, setAdvOpen] = useState(pick.changed);
  const closeIds = new Set(pick.ticked.map((ad) => ad.entity_id));
  const declined = new Set(pick.declined);
  const all = servedCleanupAds(cleanup);
  const nClose = closeIds.size;
  const nKeep = all.length - nClose;
  const reason = (ad: QueueCleanupAd) => extras.reasons.get(ad.entity_id);
  const label = (ad: QueueCleanupAd) => cleanupWord(rules, ad, reason(ad));
  const verdict = rules?.labels.verdict;
  const cap = capOf(triage.target);
  const breakEven = triage.target.break_even ?? null;
  const breakEvenCurrency = triage.target.break_even_unit?.currency ?? null;
  const rulerAds: RulerAd[] = all.map((ad) => ({
    id: ad.entity_id, name: ad.name ?? "（未命名廣告）", grade: ad.grade, gradeLabel: label(ad),
    costPerResult: ad.cost_per_result, spend: ad.spend, thumbnailUrl: ad.thumbnail_url,
    currency: ad.currency, comparisonReason: ad.cap_comparison?.reason,
    comparisonMessage: ad.cap_comparison?.message,
  }));
  const scaleHref = cleanup.scale_owner_id ? proposeBudgetPath(brandId, campaignId, cleanup.scale_owner_id) : null;
  const capText = capacityText(cleanup, extras.daily);
  // Over capacity because of the user's own unticks — the backend's `short` banner already covers its own cut.
  const overCapacity = pick.changed && cleanup.can_support !== null && nKeep > cleanup.can_support;

  return (
    <>
      <div className="flex max-w-[1260px] flex-col gap-4">
        <FlowHeader
          steps={cleanupSteps()}
          current={0}
          title={`關 ${nClose} 則、留 ${nKeep} 則`}
          purpose="沒賣出的一定關；預算放不下的，再關最貴的"
          aside={(
            <div className="flex items-center gap-2.5">
              <CapDots keep={nKeep} close={nClose} label={`留 ${nKeep} 則、關 ${nClose} 則`} />
              <span className="numeric text-sm text-muted-foreground">{capText}</span>
            </div>
          )}
          context={(
            <>
              <CampaignChip objective={triage.campaign_objective ?? "other"} name={cleanup.campaign_name} />
              {position && <span>第 {position.pos} 件／共 {position.total} 件</span>}
            </>
          )}
        />

        {extras.failed && (
          <ReadFailed what="每日預算與等級說明讀不到；下面關與留的清單照舊" onRetry={extras.retry} />
        )}

        <section className="surface px-[22px] py-5" aria-label="對照上限">
          <div className="mb-3.5 flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-[15px] font-semibold">對照上限</h2>
            <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-muted-foreground">
              <span className="inline-flex items-center gap-1.5"><i aria-hidden="true" className="inline-block size-2 rounded-sm bg-danger" />要關的</span>
              {cap && <span>{cap.basis === "break_even" ? "暫用打平" : "上限"} {formatAmount(cap.value)} {unit(cap.currency)}</span>}
            </div>
          </div>
          <TargetRuler ads={rulerAds} cap={cap} breakEven={breakEven} breakEvenCurrency={triage.target.break_even_unit?.currency ?? null} size="full" highlight={{ mode: "close", ids: [...closeIds] }} />
          <GradeRules breakEven={breakEven} />
        </section>

        {overCapacity && (
          <ResultHero
            tone="warn"
            mark="!"
            title={extras.daily === null
              ? `留 ${nKeep} 則，預算只撐得起 ${cleanup.can_support} 則`
              : `留 ${nKeep} 則，每日 ${formatAmount(extras.daily)} 只撐得起 ${cleanup.can_support} 則`}
            note="每則分到的錢變少，要更久才看得出好壞"
          />
        )}

        {cleanup.short > 0 && (
          <ResultHero
            tone="warn"
            mark="＋"
            title={shortTitle(cleanup, scaleHref !== null)}
            note={scaleHref ? <Button asChild variant="outline" size="sm" className="mt-1"><Link to={scaleHref}>看加預算提議</Link></Button> : undefined}
          />
        )}

        {cleanup.ads.length > 0 && (
          <details className="group surface" open={advOpen} onToggle={(e) => setAdvOpen(e.currentTarget.open)}>
            <summary className="flex cursor-pointer list-none items-center gap-2 px-[22px] py-3.5 text-sm font-medium [&::-webkit-details-marker]:hidden">
              <span aria-hidden="true" className="text-muted-foreground transition-transform group-open:rotate-90">›</span>
              進階：自己挑要關哪幾則
              {pick.changed && <Chip tone="accent">你留下了 {pick.declined.length} 則</Chip>}
            </summary>
            <div className="border-t border-border px-[22px] py-3">
              {cleanup.ads.map((ad) => (
                <PickRow
                  key={ad.entity_id}
                  checked={pick.isTicked(ad.entity_id)}
                  onChange={(on) => pick.toggle(ad.entity_id, on)}
                  name={ad.name ?? "（未命名廣告）"}
                  thumbnailUrl={ad.thumbnail_url}
                  grade={ad.grade}
                  gradeLabel={label(ad)}
                  aside={pickAside(ad, breakEven, breakEvenCurrency)}
                />
              ))}
              {pick.changed && (
                <Button variant="link" className="mt-2.5 h-auto px-0" onClick={pick.reset}>全部照建議關</Button>
              )}
            </div>
          </details>
        )}

        <section className="surface px-[22px] py-5" aria-label="關的順序">
          <div className="mb-3.5 flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-[15px] font-semibold">關的順序</h2>
            {verdict && (
              <span className="text-xs text-muted-foreground">照每筆成本排名；{verdict.replace}的從最後一名往前關，{verdict.keep}的不關</span>
            )}
          </div>
          <ol>
            {all.map((ad) => {
              const closing = closeIds.has(ad.entity_id);
              const mine = declined.has(ad.entity_id);
              return (
                <li key={ad.entity_id} data-ad={ad.entity_id} className="grid grid-cols-[36px_32px_minmax(0,1fr)_auto_minmax(90px,auto)_auto] items-center gap-3.5 border-t border-border py-[11px] first:border-t-0">
                  <span data-part="rank" className="text-right text-xs text-muted-foreground tabular-nums">{placeText(ad)}</span>
                  <Tile url={ad.thumbnail_url} size="sm" />
                  <div className="text-sm font-medium [overflow-wrap:anywhere]">
                    <CleanupName ad={ad} word={label(ad)} />
                  </div>
                  <CleanupGrade ad={ad} reasonCode={reason(ad)} />
                  <div className="numeric text-right"><CostCell ad={ad} word={label(ad)} breakEven={breakEven} breakEvenCurrency={breakEvenCurrency} /></div>
                  <Chip tone={closing ? "bad" : mine ? "accent" : "ok"}>{closing ? "關" : mine ? "留・你改的" : "留"}</Chip>
                </li>
              );
            })}
          </ol>
        </section>
      </div>
      <div className="flex-1" />
      {/* Nothing is written on this step: the decision is open, so the flow's one exit replaces 「← 投放中心」. */}
      <ActionBar back={{ label: "投放中心", to: homeHref }} exit={{ label: "先不要，回投放中心", to: homeHref }}>
        <Button asChild><Link to={pick.href("confirm")}>下一步：確認 →</Link></Button>
      </ActionBar>
    </>
  );
}
