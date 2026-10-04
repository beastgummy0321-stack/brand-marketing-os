import { useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { dismissSuggestion, type MonthRejectedCard } from "@/lib/adsMonthApi";
import { CampaignChip, GradeTermChip, gradeWord, useAdsRules, type ObjectiveKey } from "../patterns";
import { cleanupHref, mmdd } from "./monthCsv";

/** F29-I15: a cleanup the user rejected comes back only when one of its ads now grades worse than when the user
 * said no (Feature F29 Contract B/C `rejected.worse`, prototype v10 `rejectedSplit()` + worse cards). The rest only
 * count in the footnote. 看提議 opens that campaign's cleanup proposal, where the worsened ad is back in the list;
 * 先不要 is the month's `cleanup:<campaign_id>` dismissal (the same store as the cleanup suggestion), so the card stays
 * gone for this month. */

export function RejectedCard({ brandId, month, card, objective, onDismissed }: {
  brandId: string; month: string; card: MonthRejectedCard; objective: ObjectiveKey; onDismissed: () => void;
}) {
  const many = card.ads.length > 1;
  const rules = useAdsRules();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const skip = () => {
    setBusy(true);
    setError("");
    dismissSuggestion(brandId, month, `cleanup:${card.campaign_id}`)
      .then(onDismissed)
      .catch((err: unknown) => {
        setBusy(false);
        setError(err instanceof Error ? err.message : "先不要沒有存到，請稍後再試。");
      });
  };
  return (
    <section aria-label={card.title} data-part="rejected-worse" className="surface flex flex-col !border-danger/35 px-[22px] py-5">
      <CampaignChip objective={objective} name={card.campaign_name} />
      <b className="mt-2.5 mb-2 block text-[15px] font-semibold [overflow-wrap:anywhere]">{card.title}</b>
      {card.ads.map((ad) => (
        <div key={ad.entity_id} className="mb-1">
          {many && <div className="mb-1 text-xs text-muted-foreground [overflow-wrap:anywhere]">{ad.name ?? "（未命名廣告）"}</div>}
          <div className="flex flex-wrap items-center gap-1.5">
            <GradeTermChip grade={ad.was} />
            <span aria-hidden="true" className="text-muted-foreground">→</span>
            <GradeTermChip grade={ad.now} />
          </div>
          {rules && (
            <div className="mt-1.5 text-[13px] font-semibold">上次你拒絕時是{gradeWord(rules, ad.was)}，現在變{gradeWord(rules, ad.now)}</div>
          )}
        </div>
      ))}
      <div className="mt-0.5 mb-3.5 text-xs text-muted-foreground">
        {mmdd(card.at)} 拒絕{card.reason ? `・原因：${card.reason}` : ""}
      </div>
      {error && <p role="alert" className="mb-2 text-xs text-danger">{error}</p>}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="outline" asChild><Link to={cleanupHref(brandId, card.campaign_id)}>看提議（核准或拒絕）→</Link></Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={skip}>先不要</Button>
      </div>
    </section>
  );
}

/** The dashed footnote: the other remembered 「no」s that did not get worse, then the trend against the same days of
 * last month — a reference only, no decision reads it. */
export function MonthFootnote({ sameCount, trend }: { sameCount: number; trend: string | null }) {
  if (sameCount === 0 && trend === null) return null;
  return (
    <div data-part="month-foot" className="mt-5 border-t border-dashed border-border pt-3 text-xs text-muted-foreground">
      {sameCount > 0 && <div>你拒絕過的另外 {sameCount} 件沒有變差，這裡不再提。</div>}
      {trend !== null && <div>{trend}</div>}
    </div>
  );
}
