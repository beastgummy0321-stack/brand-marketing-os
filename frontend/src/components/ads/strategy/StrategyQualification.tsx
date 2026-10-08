import type { BudgetAdvice } from "@/lib/adsStrategyTypes";
import type { ContinuationProjection } from "@/lib/adsWizardApi";
import { Chip, Disclosure, formatAmount } from "../patterns";

const REASONS: Record<string, string> = {
  on_target_affordable: "目前成本達標，已知預算可負擔",
  cost_watch: "成本接近上限，先改善再調預算",
  cost_over: "成本超過上限，先改善再調預算",
  cost_wasted: "尚無成果且已達浪費門檻，先處理投放",
  period_budget_exceeded: "這期金額超過已確認的預算或可用資金",
  budget_unverified: "可負擔的預算尚未核實",
  coverage_unverified: "來源期間的投放資料尚未完整核實",
  coverage_unknown: "來源期間的投放資料尚未完整核實",
  planning_currency_unverified: "來源金額幣別尚未核實，不能套用台幣規劃",
  planning_currency_mismatch: "來源金額不是台幣，不能套用台幣規劃",
  continuation_outside_recent_window: "選定來源月份已不在近期預算判斷期間",
  continuation_source_unverified: "選定來源或月份尚未核實",
  objective_family_mismatch: "投放目標不同，僅保留歷史",
  objective_unknown: "來源投放目標尚未核實",
  mapping_required: "商品關聯尚未確認",
  other_product: "來源屬於不同商品",
  current_target_not_met: "目前成本未達這期上限",
  above_target: "來源成本超過上限，不能當作成功沿用",
  material_unavailable: "原素材無法取得，不能沿用",
  coordinates_unknown: "原廣告的受眾與訊息安排尚未核實",
  target_unknown: "成本上限尚未核實",
  target_unit_unknown: "成本上限的幣別或成果單位尚未核實",
  cap_currency_unknown: "成本上限幣別尚未核實",
  cap_currency_mismatch: "成果成本與上限幣別不同",
  currency_unknown: "成果成本幣別尚未核實",
  result_kind_mismatch: "成果類型不同，不能直接比較",
  result_definition_unverified: "成果計算與歸因方式尚未核實",
  measurement_changed: "成果計算或歸因方式已改變",
  small_sample: "樣本少，僅供測試或對照",
};

export function qualificationReason(code: string): string {
  return REASONS[code] ?? `來源條件尚未符合（${code}）`;
}

const ADVICE: Record<BudgetAdvice["state"], string> = {
  retain: "可維持已知預算",
  repair_before_budget: "先改善成本，再調預算",
  insufficient_evidence: "證據不足，暫無建議金額",
  unaffordable: "已知資金不足，暫無建議金額",
};

/** Served advice owns both the verdict and its evidence; the screen computes no eligibility. */
export function BudgetAdviceView({ advice, legacyRecommendation = false }: { advice: BudgetAdvice | null | undefined; legacyRecommendation?: boolean }) {
  return <div data-slot="budget-advice" className="mb-3 text-[13px]">
    <Chip tone={advice?.state === "retain" ? "accent" : "neutral"}>
      {advice ? ADVICE[advice.state] : legacyRecommendation ? "預算建議狀態尚未核實" : "目前沒有可自動建議的預算"}
    </Chip>
    {advice?.evidence.sample_flag.few === true && <span className="ml-2"><Chip>樣本少</Chip></span>}
    {advice && <Disclosure label="預算建議依據">
      <ul className="space-y-1 text-muted-foreground">
        {advice.reason_codes.map(code => <li key={code}>{qualificationReason(code)}</li>)}
      </ul>
      <dl className="mt-2 grid grid-cols-1 gap-2 text-xs sm:grid-cols-2 [overflow-wrap:anywhere]">
        <div><dt className="text-muted-foreground">判斷期間</dt><dd>{advice.evidence.window.start} 至 {advice.evidence.window.end}</dd></div>
        <div><dt className="text-muted-foreground">來源每筆成本</dt><dd>{advice.evidence.currency ?? "幣別未知"} {formatAmount(advice.evidence.cost_per_result) ?? "未知"}</dd></div>
        <div><dt className="text-muted-foreground">判斷上限（來源值）</dt><dd>{typeof advice.evidence.target.unit.currency === "string" ? advice.evidence.target.unit.currency : "幣別未知"} {formatAmount(advice.evidence.target.value) ?? "未知"}</dd></div>
        <div><dt className="text-muted-foreground">成果與歸因（來源值）</dt><dd>{advice.evidence.attribution ? [advice.evidence.attribution.kind, advice.evidence.attribution.action, advice.evidence.attribution.window].map(v => v ?? "未知").join("・") : "尚未核實"}</dd></div>
        <div><dt className="text-muted-foreground">建議版本</dt><dd>{advice.revision}</dd></div>
      </dl>
    </Disclosure>}
  </div>;
}

export function ContinuationEvidence({ source }: { source: ContinuationProjection | null | undefined }) {
  if (!source) return null;
  return <div data-slot="continuation-evidence" className="border-b border-border px-[22px] py-3 text-[13px] [overflow-wrap:anywhere]">
    <p className="text-xs text-muted-foreground">選定的下一期來源・{source.month}</p>
    {source.source_campaigns.map(c => <p key={c.campaign_id} className="mt-1 font-medium">{c.name} <span className="font-normal text-xs text-muted-foreground">{c.origin === "imported" ? "平台原生來源" : "系統活動來源"}</span></p>)}
    <Disclosure label="下一期來源與限制">
      <dl className="space-y-1 text-xs">
        <div><dt className="text-muted-foreground">來源期間</dt><dd>{source.window.start} 至 {source.window.end}</dd></div>
        <div><dt className="text-muted-foreground">來源版本</dt><dd>{source.revision}</dd></div>
        <div><dt className="text-muted-foreground">可參考引用</dt><dd>{source.eligible_learning_refs.length} 條；用途以各項依據列示為準</dd></div>
      </dl>
      {source.excluded.length > 0 ? <ul className="mt-2 space-y-2 text-xs">
        {source.excluded.map((row, i) => <li key={`${row.owner}:${row.ref}:${i}`}>{qualificationReason(row.reason_code)}<span className="block text-muted-foreground">來源識別：{row.ref}</span></li>)}
      </ul> : <p className="mt-2 text-xs text-muted-foreground">未另列排除項目；新測試仍待驗證。</p>}
    </Disclosure>
  </div>;
}
