import { Skeleton } from "@/components/layout/Skeleton";
import type { CampaignDetail } from "@/lib/adsApi";
import type { TriageSampleView } from "@/lib/adsTriageApi";
import { getCampaignStructure, type StructureAd, type StructureGroup } from "@/lib/adsWorkspaceApi";
import { useApiRead } from "@/lib/useApiRead";
import { perSaleAmount } from "../patterns/csv";
import {
  Chip, GradeRules, GradeTermChip, MoneyTag, ReadFailed, Term, TreeRows, formatAmount, gradeWord, useAdsRules,
  type AdsRules, type TreeGroup, type TreeLeaf,
} from "../patterns";

/** v10 (F30-I08) the structure tab's tree (prototype `tabStructure()`): campaign → ad groups (每日・N 則) → ads, from
 * `GET …/structure` (app-built: plan groups; imported: platform ad sets). A leaf on a platform shows its grade chip (or
 * 關閉中 while an approved pause is unconfirmed, dimmed) and its cost per result with the money fact: 沒賣出 prints
 * 「0 筆」, a thin sample prints its label, an unknown cost prints 「—」 (never 0). A planned ad not on a platform yet
 * shows no grade; one without ready material is the dashed 缺素材 tile. The grade legend shows once, under the tree.
 * A failed read is `ReadFailed` with 重試; the editors below the card stay usable. `planKey` re-reads the tree after a
 * plan edit (a new group, a renamed ad, a new daily budget). */

const CARD = "surface px-[22px] py-5";
const HEAD = "mb-3.5 flex flex-wrap items-center justify-between gap-3";
const H2 = "text-[15px] font-semibold";

const daily = (v: number | null) => `每日 ${formatAmount(v) ?? "—"}`;

/** F48 Contract R: `GET …/structure` serves each ad's `reason_code` and `sample` beside its grade
 * (`app/ads/workspace_reads.py`); `StructureAd` in `lib/adsWorkspaceApi.ts` (outside this issue's scope) does not
 * declare them yet, so they are read through this one view until it does. */
type GradedStructureAd = StructureAd & { reason_code?: string | null; sample?: TriageSampleView | null };

function leafValue(a: GradedStructureAd, breakEven: number | null, rules: AdsRules | null) {
  if (a.grade === "wasted") return "0 筆";
  if (a.grade === "insufficient") {
    const thin = !a.reason_code || a.reason_code === "too_new";
    const label = a.grade_label || gradeWord(rules, a.grade, a.reason_code) || "";
    // Beside the chip that already says it: wraps onto two short lines so the ad name keeps its width at 1024.
    return <span className="inline-block max-w-[5.5rem] font-normal leading-snug text-muted-foreground">{thin ? <Term k="thin">{label}</Term> : label}</span>;
  }
  const cost = perSaleAmount(a.cost_per_result);
  return cost === null ? "—" : <>{cost} 元<MoneyTag cost={a.cost_per_result} breakEven={breakEven} /></>;
}

function leafOf(a: GradedStructureAd, i: number, breakEven: number | null, rules: AdsRules | null): TreeLeaf {
  const key = a.entity_id ?? a.ad_id ?? `ad-${i}`;
  if (a.missing_material) return { key, name: a.name, thumbnailUrl: null, missing: true };
  // Not on a platform yet: nothing to grade, nothing spent.
  if (a.entity_id === null) return { key, name: a.name, thumbnailUrl: a.thumbnail_url };
  return {
    key, name: a.name, thumbnailUrl: a.thumbnail_url, dimmed: a.closing,
    chip: a.closing ? <Chip>關閉中</Chip> : <GradeTermChip grade={a.grade} label={a.grade_label} reasonCode={a.reason_code} />,
    value: leafValue(a, breakEven, rules),
  };
}

function groupOf(g: StructureGroup, i: number, breakEven: number | null, rules: AdsRules | null): TreeGroup {
  return {
    key: g.group_id ?? `group-${i}`, kind: "廣告組", name: g.name,
    note: `${daily(g.daily_budget)}・${g.ads.length} 則`,
    leaves: g.ads.map((a, j) => leafOf(a, j, breakEven, rules)),
  };
}

export function StructureTab({ brandId, campaign: c, planKey }: {
  brandId: string;
  campaign: CampaignDetail;
  /** Changes whenever the plan behind the tree changes; a new value re-reads the structure. */
  planKey: string;
}) {
  const read = useApiRead((signal) => getCampaignStructure(brandId, c.id, signal), [brandId, c.id, planKey]);
  const data = read.data;
  const rules = useAdsRules();
  const groups = data?.groups ?? [];
  // The campaign's daily total only when every group's daily budget is known; one unknown makes the total unknown.
  const total = groups.length && groups.every((g) => g.daily_budget !== null)
    ? groups.reduce((sum, g) => sum + (g.daily_budget ?? 0), 0) : null;
  const perResult = c.cap.result_kind === "purchase" ? "每賣一筆" : `每一筆${c.cap.result_label}`;

  return (
    <section className={CARD} aria-label="投放結構">
      <div className={HEAD}>
        <h2 className={H2}>活動 → 廣告組 → 廣告</h2>
        <span className="text-xs text-muted-foreground">每則右邊是{perResult}花多少</span>
      </div>
      {read.status === "error" && (
        <ReadFailed what={`投放結構讀不到：${read.error}　下方「進階」的編輯仍可使用。`} onRetry={read.reload} />
      )}
      {read.status === "loading" && !data && <Skeleton className="h-48 w-full" />}
      {data && groups.length === 0 && (
        <p className="text-sm text-muted-foreground">
          {c.origin === "imported" ? "還沒讀回平台上的廣告組。" : "這個活動還沒有廣告組。"}
        </p>
      )}
      {data && groups.length > 0 && (
        <>
          <TreeRows
            root={{ kind: "活動", name: c.name, note: (
              // An imported objective can be a whole sentence: two lines at most, the full text on hover.
              <span className="line-clamp-2" title={c.objective || undefined}>{`${daily(total)}・${c.objective || "目標待確認"}`}</span>
            ) }}
            groups={groups.map((g, i) => groupOf(g, i, c.cap.break_even, rules))}
          />
          <GradeRules breakEven={c.cap.break_even} />
        </>
      )}
    </section>
  );
}
