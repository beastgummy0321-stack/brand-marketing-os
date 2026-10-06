import type { StrategyDecision, StrategyRole } from "@/lib/adsStrategyTypes";

/** Bindings and counts are served together; the browser neither pairs names nor estimates capacity. */
export function StrategyCommitments({ decision, role, stale, details = false }: {
  decision: StrategyDecision | undefined; role: StrategyRole; stale: boolean; details?: boolean;
}) {
  const slots = decision?.slots.filter((slot) => slot.role === role) ?? [];
  return (
    <ul className="mt-2 space-y-2">
      {slots.map((slot) => (
        <li key={slot.id} data-slot="strategy-commitment" className="border-l-2 border-border pl-3 text-[13px] [overflow-wrap:anywhere]">
          <p className="font-medium">{slot.display?.customer_group_label ?? "顧客群名稱未提供"}・{slot.display?.offer_label ?? "優惠名稱未提供"}</p>
          {!details && <p className="text-muted-foreground">
            {slot.carry_from_ad_id === null ? `新測試：${slot.test_intent ?? "測試目的未提供"}` : `保留原廣告：${slot.display?.carried_ad_label ?? "原廣告名稱未提供"}`}
          </p>}
          {details && !stale && <p className="mt-1">{typeof slot.rationale === "string" ? slot.rationale : "安排理由未提供"}</p>}
          {details && !stale && <div className="mt-1 text-xs text-muted-foreground">
            {(slot.display?.evidence ?? []).map((ref) => <p key={`${ref.kind}:${ref.id}`} title={ref.id}>依據：{ref.label}</p>)}
            {(slot.evidence_refs?.length ?? 0) === 0 && <p>沒有可引用的投放紀錄；這則安排是待驗證的新假設。</p>}
            {!!slot.display?.evidence_omitted && <p>另有 {slot.display.evidence_omitted} 項依據，此處只顯示前三項。</p>}
          </div>}
        </li>
      ))}
    </ul>
  );
}

export function StrategyAssignmentSummary({ decision }: { decision: StrategyDecision | undefined }) {
  const facts = decision?.facts;
  if (!facts) return <p className="mb-3 text-xs text-muted-foreground">安排統計尚未提供，請重新產生並確認策略。</p>;
  return (
    <dl data-slot="assignment-summary" className="mb-3 grid grid-cols-1 gap-2 border-b border-border pb-3 text-[13px] sm:grid-cols-3">
      <div><dt className="text-muted-foreground">可選顧客群</dt><dd>{facts.available.customer_groups} 群</dd></div>
      <div><dt className="text-muted-foreground">提議安排</dt><dd>{facts.proposed.customer_groups} 群・{facts.proposed.delivery_groups} 個投放組・{facts.proposed.ads} 則廣告</dd>
        {facts.proposed.unknown_audience_ads > 0 && <dd className="text-muted-foreground">{facts.proposed.unknown_audience_ads} 則尚未指定顧客群</dd>}</div>
      <div><dt className="text-muted-foreground">實際投放結構</dt><dd>{facts.actual.customer_groups} 群・{facts.actual.delivery_groups} 個投放組・{facts.actual.ads} 則廣告</dd>
        {facts.actual.unknown_audience_ads > 0 && <dd className="text-muted-foreground">{facts.actual.unknown_audience_ads} 則尚未指定顧客群</dd>}</div>
    </dl>
  );
}
