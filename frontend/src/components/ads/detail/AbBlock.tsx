import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { getAbPairs, pauseAbLoser, type AbPair as AbPairView } from "@/lib/adsAbApi";
import type { QueuePauseProposal } from "@/lib/adsTriageApi";
import { readErrorMessage, useApiRead } from "@/lib/useApiRead";
import { AbPair, Chip, Disclosure, ReadFailed, Term, formatAmount } from "../patterns";
import { proposalAction } from "../home/status";

/** F29-I13: the campaign detail's automatic A/B block (prototype v10 `abBlock()` + `abPair()`, hash `camp/daily/perf`),
 * between the ruler card and the grade groups. Pairs come from `GET …/ab-pairs` (Contract F) as they are; the kit
 * `AbPair` draws each one and this file only picks the action that fits `pair.decision`:
 * none → 「關掉輸家（X）→」 (creates the `source: "ab"` pause set, then opens its confirm step); a draft set → the same
 * button straight to that set's confirm step; approved → 等你到 Meta 完成／等核對 + 繼續; confirmed → ✓ 已關掉;
 * rejected／deferred → 你決定兩則都留. No pairs (imported campaigns included) → no card at all; a failed read is its
 * own state, never an empty block. */

const changeHref = (brandId: string, campaignId: string, setId: string) =>
  `/brands/${brandId}/ads/campaigns/${campaignId}/changes/${setId}/confirm`;

function Decided({ brandId, campaignId, pair, loser }: { brandId: string; campaignId: string; pair: AbPairView; loser: "A" | "B" }) {
  const d = pair.decision!;
  if (d.status === "rejected" || d.status === "deferred") return <Chip>你決定兩則都留</Chip>;
  if (d.status === "draft") {
    return <Button asChild><Link to={changeHref(brandId, campaignId, d.change_set_id)}>關掉輸家（{loser}）→</Link></Button>;
  }
  // approved: the same step routing every other change set uses (home/status.ts), fed a pause-shaped proposal.
  const proposal: QueuePauseProposal = {
    kind: "pause", change_set_id: d.change_set_id, campaign_id: campaignId, status: "approved",
    verification_state: d.verification_state ?? "pending", reason: null, revisit_at: null, multi: false,
  };
  const step = proposalAction(brandId, campaignId, campaignId, proposal);
  if (step.done) return <Chip tone="ok">✓ 已關掉 {loser}・寫進<Term k="notebook">筆記本</Term></Chip>;
  const waiting = proposal.verification_state === "pending";
  return (
    <>
      <Chip tone={waiting ? "accent" : "warn"}>{waiting ? "已核准・等你到 Meta 完成" : `已核准・${step.label}`}</Chip>
      <Button size="sm" variant="outline" asChild><Link to={step.href}>繼續 →</Link></Button>
    </>
  );
}

export function AbBlock({ brandId, campaignId, breakEven }: { brandId: string; campaignId: string; breakEven: number | null }) {
  const read = useApiRead((signal) => getAbPairs(brandId, campaignId, signal), [brandId, campaignId]);
  const navigate = useNavigate();
  const [busy, setBusy] = useState<string | null>(null);
  const [failed, setFailed] = useState<Record<string, string>>({});
  // One operation id per pair for this visit: a retry after a lost answer replays the same set.
  const operations = useRef(new Map<string, string>());

  if (read.status === "error") {
    return <ReadFailed what={`兩則比較讀不到（${read.error}）；上面的成績和下面的廣告照常可看。`} onRetry={read.reload} />;
  }
  const pairs = read.data?.pairs ?? [];
  if (!pairs.length) return null;
  const rules = pairs[0].rules;

  async function pauseLoser(pair: AbPairView) {
    let op = operations.current.get(pair.pair_id);
    if (!op) {
      op = crypto.randomUUID();
      operations.current.set(pair.pair_id, op);
    }
    setBusy(pair.pair_id);
    setFailed((prev) => { const next = { ...prev }; delete next[pair.pair_id]; return next; });
    try {
      const set = await pauseAbLoser(brandId, campaignId, pair.pair_id, op);
      navigate(changeHref(brandId, campaignId, set.id));
    } catch (err) {
      setFailed((prev) => ({ ...prev, [pair.pair_id]: readErrorMessage(err) }));
      setBusy(null);
    }
  }

  function action(pair: AbPairView) {
    if (pair.state !== "judged" || pair.winner === null) return undefined;
    const loser = pair.winner === "a" ? "B" : "A";
    if (pair.decision && pair.decision.status !== "superseded") {
      return <Decided brandId={brandId} campaignId={campaignId} pair={pair} loser={loser} />;
    }
    return (
      <Button onClick={() => void pauseLoser(pair)} disabled={busy === pair.pair_id}>
        {busy === pair.pair_id ? "建立中…" : `關掉輸家（${loser}）→`}
      </Button>
    );
  }

  return (
    <section className="surface px-[22px] py-5" aria-label="兩則只差一處的比較" data-testid="ab-block">
      <div className="mb-3.5 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-[15px] font-semibold">兩則只差一處的比較</h2>
        <Chip>{pairs.length} 組</Chip>
      </div>
      <div className="flex flex-col gap-4">
        {pairs.map((pair, i) => (
          <div key={pair.pair_id} className="flex flex-col gap-4">
            {i > 0 && <div className="border-t border-border" />}
            <AbPair pair={pair} breakEven={breakEven} action={action(pair)} />
            {failed[pair.pair_id] && (
              <p role="alert" className="text-sm font-medium text-danger">關掉輸家沒建立成：{failed[pair.pair_id]}</p>
            )}
          </div>
        ))}
      </div>
      <div className="mt-3.5">
        <Disclosure label="怎麼比的">
          <div className="text-sm leading-[1.8] text-muted-foreground">
            同一個廣告組裡、只差一處的兩則自動配成一組<br />
            兩則都投滿 {rules.min_days} 天、各有 {rules.min_conversions_each} 筆購買，每筆差 {formatAmount(rules.relative_difference * 10)} 成以上才判斷<br />
            兩則拿到的錢不一定一樣多
          </div>
        </Disclosure>
      </div>
    </section>
  );
}
