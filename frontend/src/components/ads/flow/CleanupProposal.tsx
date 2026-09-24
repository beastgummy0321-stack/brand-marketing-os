import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { getTriage, type QueueCleanup, type QueueCleanupAd, type QueueItem, type TriageGrade, type TriageTargetView } from "@/lib/adsTriageApi";
import {
  ActionBar, CampaignChip, CapDots, Chip, FlowHeader, GRADE_LABEL, GradeChip, ResultHero, TargetRuler, formatAmount,
  type FlowStep, type RulerAd, type RulerCap,
} from "../patterns";
import { proposeBudgetPath } from "./changeFlow";
import { Tile } from "./Tile";

/** F28-I11: the cleanup proposal step (prototype v9 `stepProp()` for kind `clean`, hash `d/clean/prop`). The light
 * flow is 提議 → 確認 → 到平台完成 → 核對結果; this step only shows the queue row's `cleanup` payload (F28-I02) —
 * nothing is written until 核准 on the confirm step (`ConfirmPage`, lazy create unchanged). */

export function cleanupSteps(proposeHref?: string): FlowStep[] {
  return [{ label: "提議", to: proposeHref }, { label: "確認" }, { label: "到平台完成" }, { label: "核對結果" }];
}

/** Close order (ads.md §6.32): 白花 → 太貴 → 偏貴 → 划算 → 還太新, the most expensive first inside a grade; an unknown
 * cost sorts first (prototype `cost ?? 1e9`), then higher spend. */
const RANK: Record<TriageGrade, number> = { wasted: 0, over: 1, watch: 2, on_target: 3, insufficient: 4, no_target: 5 };
const desc = (v: number | null) => (v === null ? Number.POSITIVE_INFINITY : v);
export function rankCleanupAds(ads: QueueCleanupAd[]): QueueCleanupAd[] {
  return [...ads].sort((x, y) =>
    RANK[x.grade] - RANK[y.grade]
    || desc(y.cost_per_result) - desc(x.cost_per_result)
    || desc(y.spend) - desc(x.spend));
}

const money = (v: number | null) => (formatAmount(v) === null ? "未知" : `${formatAmount(v)} 元`);

/** The number cell of a row: 白花 prints its result count, 還太新 is not a cost yet, the rest print cost per result. */
export function CostCell({ ad, label, withCaption = false }: { ad: QueueCleanupAd; label: string; withCaption?: boolean }): ReactNode {
  if (ad.grade === "wasted") {
    const count = ad.result_count === null ? "未知" : `${ad.result_count} 筆`;
    return <>{withCaption && <span className="block text-[11.5px] text-muted-foreground">購買</span>}<b className="text-[15px]">{count}</b></>;
  }
  if (ad.grade === "insufficient" || ad.grade === "no_target") {
    return <span className="font-medium text-muted-foreground">{label === "資料不足" ? "資料不足" : ad.grade === "no_target" ? "未判斷" : "還太新"}</span>;
  }
  return <>{withCaption && <span className="block text-[11.5px] text-muted-foreground">每賣一筆</span>}<b className="text-[15px]">{money(ad.cost_per_result)}</b></>;
}

function capOf(target: TriageTargetView): RulerCap | null {
  return target.value === null || target.basis === null ? null : { value: target.value, basis: target.basis };
}
/** Triage `target` is the F28 cap view; `break_even` is not declared on `TriageTargetView` (same read as I10). */
function breakEvenOf(target: TriageTargetView): number | null {
  const value = (target as TriageTargetView & { break_even?: number | null }).break_even;
  return typeof value === "number" ? value : null;
}

/** 「每日 1,200 撐 6 則」: the daily budget is only on the campaign triage (`data.capacity`), read on its own so a
 * failure leaves the words without the amount, never the page blank. Grade words of 還太新 vs 資料不足 come from the
 * same read (the cleanup payload carries `grade` only). */
function useCampaignExtras(brandId: string, campaignId: string) {
  const [extras, setExtras] = useState<{ daily: number | null; labels: Map<string, string> }>({ daily: null, labels: new Map() });
  useEffect(() => {
    let cancelled = false;
    getTriage(brandId, campaignId)
      .then((t) => {
        if (cancelled || !t) return;
        setExtras({
          daily: t.data?.capacity?.daily_budget ?? null,
          labels: new Map((t.items ?? []).map((i) => [i.entity_id, i.grade_label])),
        });
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [brandId, campaignId]);
  return extras;
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

export function CleanupProposal({ brandId, campaignId, item, position, homeHref }: {
  brandId: string; campaignId: string; item: QueueItem & { cleanup: QueueCleanup };
  position: { pos: number; total: number } | null; homeHref: string;
}) {
  const { cleanup, triage } = item;
  const extras = useCampaignExtras(brandId, campaignId);
  const closeIds = new Set(cleanup.ads.map((ad) => ad.entity_id));
  const all = rankCleanupAds([...cleanup.ads, ...cleanup.keep]);
  const label = (ad: QueueCleanupAd) => extras.labels.get(ad.entity_id) || GRADE_LABEL[ad.grade];
  const cap = capOf(triage.target);
  const rulerAds: RulerAd[] = all.map((ad) => ({
    id: ad.entity_id, name: ad.name ?? "（未命名廣告）", grade: ad.grade, gradeLabel: label(ad),
    costPerResult: ad.cost_per_result, spend: ad.spend, thumbnailUrl: ad.thumbnail_url,
  }));
  const scaleHref = cleanup.scale_owner_id ? proposeBudgetPath(brandId, campaignId, cleanup.scale_owner_id) : null;
  const capText = capacityText(cleanup, extras.daily);

  return (
    <>
      <div className="flex max-w-[1260px] flex-col gap-4">
        <FlowHeader
          steps={cleanupSteps()}
          current={0}
          title={`關 ${cleanup.ads.length} 則、留 ${cleanup.keep.length} 則`}
          purpose="白花的一定關；預算放不下的，再關最貴的"
          aside={(
            <div className="flex items-center gap-2.5">
              <CapDots keep={cleanup.keep.length} close={cleanup.ads.length} label={`留 ${cleanup.keep.length} 則、關 ${cleanup.ads.length} 則`} />
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

        <section className="surface px-[22px] py-5" aria-label="對照上限">
          <div className="mb-3.5 flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-[15px] font-semibold">對照上限</h2>
            <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-muted-foreground">
              <span className="inline-flex items-center gap-1.5"><i aria-hidden="true" className="inline-block size-2 rounded-sm bg-danger" />要關的</span>
              {cap && <span>{cap.basis === "break_even" ? "暫用打平" : "上限"} {formatAmount(cap.value)}</span>}
            </div>
          </div>
          <TargetRuler ads={rulerAds} cap={cap} breakEven={breakEvenOf(triage.target)} size="full" highlight={{ mode: "close", ids: [...closeIds] }} />
        </section>

        {cleanup.short > 0 && (
          <ResultHero
            tone="warn"
            mark="＋"
            title={shortTitle(cleanup, scaleHref !== null)}
            note={scaleHref ? <Button asChild variant="outline" size="sm" className="mt-1"><Link to={scaleHref}>看加預算提議</Link></Button> : undefined}
          />
        )}

        <section className="surface px-[22px] py-5" aria-label="關的順序">
          <div className="mb-3.5 flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-[15px] font-semibold">關的順序</h2>
            <span className="text-xs text-muted-foreground">白花 → 太貴 → 偏貴，同級先關最貴的；划算不關</span>
          </div>
          <ol>
            {all.map((ad, i) => {
              const closing = closeIds.has(ad.entity_id);
              return (
                <li key={ad.entity_id} className="grid grid-cols-[24px_32px_minmax(0,1fr)_auto_90px_36px] items-center gap-3.5 border-t border-border py-[11px] first:border-t-0">
                  <span className="text-right text-xs text-muted-foreground">{i + 1}</span>
                  <Tile url={ad.thumbnail_url} size="sm" />
                  <p className="text-sm font-medium [overflow-wrap:anywhere]">{ad.name ?? "（未命名廣告）"}</p>
                  <GradeChip grade={ad.grade} label={label(ad)} />
                  <div className="numeric text-right"><CostCell ad={ad} label={label(ad)} /></div>
                  <Chip tone={closing ? "bad" : "ok"}>{closing ? "關" : "留"}</Chip>
                </li>
              );
            })}
          </ol>
        </section>
      </div>
      <div className="flex-1" />
      <ActionBar back={<Button variant="ghost" asChild><Link to={homeHref}>← 投放中心</Link></Button>}>
        <Button asChild><Link to="?step=confirm">下一步：確認 →</Link></Button>
      </ActionBar>
    </>
  );
}
