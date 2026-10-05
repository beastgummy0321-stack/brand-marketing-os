import { getAbPairs, type AbPair, type AbSide } from "@/lib/adsAbApi";
import type { AbChangeBlock, AbChangeSide, ChangeItem } from "@/lib/adsChangeApi";
import { getTriage, type CampaignObjectiveFamily } from "@/lib/adsTriageApi";
import { useApiRead } from "@/lib/useApiRead";
import { Chip, KindMark, LearnLine, MoneyTag, Term, Thumb, useAdsRules } from "../patterns";
import { perSaleAmount } from "../patterns/csv";
import { daysBetween } from "@/lib/orgClock";

/** F29-I14: the A/B "pause the loser" decision (Contract F, `source: "ab"` change sets; prototype v10 `confirmBody()`
 * for kind `ab`, `stepChk()`'s learning line, hashes `d/ab/ok|plat|chk`). The set itself freezes what is approved
 * (`set.ab`: the two sides' values and cost per result); the live pair (`GET …/ab-pairs`) only adds what the set does
 * not carry — the A/B letters of the performance card the user came from and the thumbnails — and the campaign triage
 * adds the campaign chip and break-even for the money tag. Either read failing leaves the frozen numbers on screen. */

export interface AbContext {
  pair: AbPair | null;
  breakEven: number | null;
  campaign: { name: string; objective: CampaignObjectiveFamily } | null;
  failed: boolean;
  reload: () => void;
}

/** The two context reads of an `ab` set; `ab` null (any other set) reads nothing. */
export function useAbContext(brandId: string, campaignId: string, ab: AbChangeBlock | null | undefined): AbContext {
  const on = Boolean(ab);
  const pairsRead = useApiRead((signal) => (on ? getAbPairs(brandId, campaignId, signal) : Promise.resolve(null)), [brandId, campaignId, on]);
  const triageRead = useApiRead((signal) => (on ? getTriage(brandId, campaignId, signal) : Promise.resolve(null)), [brandId, campaignId, on]);
  const first = triageRead.data?.items[0];
  return {
    pair: pairsRead.data?.pairs.find((p) => p.pair_id === ab?.pair_id) ?? null,
    breakEven: first?.target.break_even ?? null,
    campaign: first ? { name: first.campaign_name, objective: first.campaign_objective ?? "other" } : null,
    failed: pairsRead.status === "error" || triageRead.status === "error",
    reload: () => { pairsRead.reload(); triageRead.reload(); },
  };
}

/** Contract F learning text — the same words `app/ads/ads_learnings.py::ab_text` writes (no numbers). */
export function abLearningText(ab: AbChangeBlock): string {
  return `「${ab.dimension_label}」用「${ab.winner.value_label}」比「${ab.loser.value_label}」划算`;
}

// F47-I06: the one per-sale rule (whole yuan, rounded, never floored).
const whole = perSaleAmount;

/** 「每筆 45 vs 56」 beside the learning (the learning itself carries no numbers); null when either cost is unknown. */
function costPair(ab: AbChangeBlock): string | null {
  const w = whole(ab.winner.cost_per_result), l = whole(ab.loser.cost_per_result);
  return w === null || l === null ? null : `每筆 ${w} vs ${l}`;
}

/** A/B letter of the loser and winner, from the live pair; null when the pair read failed or the pair is gone. */
export function abLetters(ab: AbChangeBlock, pair: AbPair | null): { loser: "A" | "B"; winner: "A" | "B" } | null {
  if (!pair) return null;
  if (pair.a.ad_id === ab.loser.ad_id) return { loser: "A", winner: "B" };
  if (pair.b.ad_id === ab.loser.ad_id) return { loser: "B", winner: "A" };
  return null;
}

/** The approve button: 「核准關掉 A」, or 「核准關掉較貴的一則」 while the letters are unknown. */
export function abApproveLabel(ab: AbChangeBlock, pair: AbPair | null): string {
  const letter = abLetters(ab, pair)?.loser;
  return letter ? `核准關掉 ${letter}` : "核准關掉較貴的一則";
}

function days(window: AbChangeBlock["window"]): number | null {
  if (!window) return null;
  return daysBetween(window.start, window.end);
}

function Letter({ k }: { k: "A" | "B" }) {
  return <span className="inline-grid size-6 shrink-0 place-items-center rounded-md bg-foreground text-xs font-bold text-white">{k}</span>;
}

function SideRow({ letter, side, live, dimension, span, close, breakEven }: {
  letter: "A" | "B" | null; side: AbChangeSide; live: AbSide | null; dimension: string; span: number | null; close: boolean;
  breakEven: number | null;
}) {
  const cost = side.cost_per_result;
  return (
    <li className="grid grid-cols-[auto_40px_minmax(0,1fr)_minmax(110px,auto)_36px] items-center gap-3.5 border-t border-border py-[11px] first:border-t-0">
      {letter ? <Letter k={letter} /> : <span />}
      <Thumb url={live?.thumbnail_url ?? null} size={40} />
      <div className="min-w-0">
        <div className="text-[11.5px] text-muted-foreground">{dimension}：{side.value_label}</div>
        <p className="text-sm font-medium [overflow-wrap:anywhere]">{side.name}</p>
      </div>
      <div className="numeric text-right">
        <span className="block text-[11.5px] text-muted-foreground">{span === null ? "每筆" : `近 ${span} 天每筆`}</span>
        <b className="text-[15px]">{cost === null ? "讀不到" : `${whole(cost)} 元`}</b>
        <MoneyTag cost={cost} breakEven={breakEven} className="block" />
      </div>
      <Chip tone={close ? "bad" : "ok"}>{close ? "關" : "留"}</Chip>
    </li>
  );
}

/** The confirm card (prototype `confirmBody()` kind `ab`): 關掉 A、留下 B, both sides with 關／留, 不會新增花費 and
 * the learning that is written once the pause reads back confirmed. */
export function AbEvidence({ ab, context }: { ab: AbChangeBlock; context: AbContext }) {
  const { pair, breakEven } = context;
  const letters = abLetters(ab, pair);
  const liveOf = (side: AbChangeSide) => (pair ? [pair.a, pair.b].find((s) => s.ad_id === side.ad_id) ?? null : null);
  const span = days(ab.window);
  // F48 Contract R-API: the pair's own rules, else the served A/B rules; while neither is loaded the sentence prints
  // without its numbers (no number is written down here).
  const served = useAdsRules();
  const rules = pair?.rules ?? served?.ab ?? null;
  const w = ab.winner.cost_per_result, l = ab.loser.cost_per_result;
  const pct = w !== null && l !== null && Math.max(w, l) > 0 ? Math.round((Math.abs(l - w) / Math.max(w, l)) * 100) : null;
  const winName = letters ? `${letters.winner} ` : `「${ab.winner.value_label}」`;
  const rows = letters
    ? (letters.loser === "A" ? [["A", ab.loser, true], ["B", ab.winner, false]] : [["A", ab.winner, false], ["B", ab.loser, true]]) as [("A" | "B"), AbChangeSide, boolean][]
    : [[null, ab.loser, true], [null, ab.winner, false]] as [null, AbChangeSide, boolean][];
  const meta = costPair(ab);
  return (
    <div className="surface px-[22px] py-5">
      <div className="flex flex-wrap items-start gap-5">
        <div className="min-w-[240px] flex-1">
          <KindMark kind="cut">只差「{ab.dimension_label}」</KindMark>
          <p className="mt-1.5 text-[26px] font-semibold tracking-tight">
            {letters ? `關掉 ${letters.loser}、留下 ${letters.winner}` : `關掉「${ab.loser.value_label}」、留下「${ab.winner.value_label}」`}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Chip tone="ok">✓ 不會新增花費</Chip>
          <Chip tone="ok">✓ 關掉不會刪除，想反悔隨時可以再開</Chip>
        </div>
      </div>
      <p className="mt-2.5 text-sm font-semibold">
        {pct !== null && `${winName}每筆便宜 ${pct}%，`}
        {rules ? `兩則都跑滿 ${rules.min_days} 天、各賣到 ${rules.min_conversions_each} 筆以上` : "兩則都跑滿天數、各賣到足夠的筆數"}
      </p>
      <ul className="mt-3.5">
        {rows.map(([letter, side, close]) => (
          <SideRow key={side.ad_id} letter={letter} side={side} live={liveOf(side)} dimension={ab.dimension_label} span={span} close={close} breakEven={breakEven} />
        ))}
      </ul>
      <div className="mt-2.5 border-t border-border">
        <LearnLine tone="ok" mark="✎" eyebrow={<>核對完成後寫進<Term k="notebook">筆記本</Term></>} title={abLearningText(ab)} meta={meta ?? undefined} />
      </div>
    </div>
  );
}

/** The verify step's learning line (prototype `stepChk()` for kind `ab`): written once the pause reads back confirmed
 * (`item.learning.recorded`, Contract F); until then it says it will be. */
export function AbLearnedCard({ ab, item }: { ab: AbChangeBlock; item: ChangeItem }) {
  const recorded = item.learning?.recorded === true;
  const meta = costPair(ab);
  return (
    <div className="surface px-[22px] py-1">
      <LearnLine
        tone="ok"
        mark="✎"
        eyebrow={recorded ? <>已寫進<Term k="notebook">筆記本</Term></> : <>核對完成後寫進<Term k="notebook">筆記本</Term></>}
        title={abLearningText(ab)}
        meta={meta ?? undefined}
      />
    </div>
  );
}
