import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { fetchClosingReview, type ClosingReview, type Cycle } from "@/lib/warroomApi";
import { formatCurrency, formatRoas } from "@/lib/format";

const VERDICT_LABELS = { supported: "成立", rejected: "不成立", inconclusive: "看不出來" } as const;

/** 覆盤（S8.59-66，全新，僅 `cycle.status === 'CLOSED'` 後出現）：固定四段式，純聚合既有
 * 資料，不重新計算任何判讀邏輯。 */
export function ReviewStep({ brandId, cycle }: { brandId: string; cycle: Cycle }) {
  const [state, setState] = useState<{ status: "loading" } | { status: "locked"; message: string } | { status: "ready"; review: ClosingReview }>({ status: "loading" });

  useEffect(() => {
    fetchClosingReview(brandId, cycle.id)
      .then((review) => setState({ status: "ready", review }))
      .catch((err: unknown) => setState({ status: "locked", message: err instanceof Error ? err.message : "這期還沒結案，覆盤要等成效判讀跑完期末結算才會出現。" }));
  }, [brandId, cycle.id]);

  if (state.status === "loading") return <div className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">讀取中…</div>;
  if (state.status === "locked") {
    return <div className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">{state.message}</div>;
  }

  const { review } = state;
  return (
    <div className="flex flex-col gap-4">
      <h2 className="font-display text-lg text-foreground">這期覆盤</h2>

      <Section title="①目標對照">
        <p className="text-sm text-foreground">目標：{review.goal_comparison.objective_label}・{review.goal_comparison.target}</p>
        <p className="mt-1 text-sm text-muted-foreground">
          實際 KPI：CTR {review.goal_comparison.actual_kpis.ctr ?? "資料不足"}、CPA {formatCurrency(review.goal_comparison.actual_kpis.cpa)}、ROAS {formatRoas(review.goal_comparison.actual_kpis.roas)}
        </p>
      </Section>

      <Section title="②落差歸因">
        <ul className="list-disc pl-4 text-sm text-foreground">
          {review.gap_attribution.reasons.map((r, i) => <li key={i}>{r}</li>)}
        </ul>
        {review.gap_attribution.channel_note && <p className="mt-1 text-xs text-muted-foreground">{review.gap_attribution.channel_note}</p>}
        {review.gap_attribution.ga4_leak_note && <p className="mt-1 text-xs text-warning">{review.gap_attribution.ga4_leak_note}</p>}
      </Section>

      <Section title="③學習兩層">
        <p className="text-xs font-medium text-muted-foreground">本期層：策略假設結案</p>
        <ul className="list-disc pl-4 text-sm text-foreground">
          {review.learning.hypotheses.map((h, i) => <li key={i}>{h.statement}：{VERDICT_LABELS[h.verdict]}</li>)}
        </ul>
        <p className="mt-2 text-xs font-medium text-muted-foreground">跨期層：累積智慧</p>
        {review.learning.ledger_entries.length === 0 ? (
          <p className="text-sm text-muted-foreground">這期沒有新入帳的累積智慧。</p>
        ) : (
          <ul className="list-disc pl-4 text-sm text-foreground">
            {review.learning.ledger_entries.map((e, i) => <li key={i}>{e.text}</li>)}
          </ul>
        )}
      </Section>

      <Section title="④具體建議">
        <p className="text-sm text-foreground">{review.recommendation.budget_advice}</p>
        <p className="mt-1 text-xs text-muted-foreground">
          建議預算 {formatCurrency(review.recommendation.proposed_budget)}・新增規則卡 {review.recommendation.rule_cards_created} 張
          {review.recommendation.echo_chamber && "・已提示避免回音室"}
        </p>
      </Section>

      <Link to={`/brands/${brandId}/campaigns/new`} className="self-start rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90">
        開下一期就這樣開
      </Link>

      <p className="text-xs text-muted-foreground">本週報告掛載點（B5 範圍，本票只留入口，內部長相延至 B5）。</p>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4 shadow-[var(--shadow-card)]">
      <p className="font-medium text-foreground">{title}</p>
      <div className="mt-1">{children}</div>
    </div>
  );
}
