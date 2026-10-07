import type { LearningEvidence } from "@/lib/adsLearningEvidence";
import { Button } from "@/components/layout/ui/button";
import { Chip, type ChipTone, formatAmount } from "./Chip";
import { Disclosure } from "./Disclosure";
import { formatDay } from "@/lib/orgClock";

const USE_LABEL: Record<LearningEvidence["use_state"], string> = {
  usable: "可參考", history: "只看歷史", revalidation: "需重新核對", excluded: "未採用",
};
const ORIGIN_LABEL: Record<LearningEvidence["provenance"], string> = {
  platform_observation: "平台結果", user_report: "使用者提供", operation_readback: "操作回讀",
  simulation: "演練資料", unknown: "來源尚未核實",
};
const SOURCE_KIND = {campaign: "活動觀察", pause: "暫停操作", ab: "對照比較", settle: "活動結案", coordinate: "廣告判讀", visual: "視覺比較"};
const LIMIT_LABEL: Record<string, string> = {
  conditions_unknown: "適用條件尚未核實", causality_unknown: "不能證明造成結果的原因",
  causal_effect_not_proven: "不能證明造成結果的原因", attribution_unknown: "成果歸因方式尚未核實",
  relative_comparison_only: "僅能比較這兩個方案", operation_only: "僅證明操作已核對",
  simulated: "演練資料不能作為市場成效", result_definition_unknown: "成果定義尚未核實",
  measurement_definition_unknown: "成果量測與歸因定義尚未核實", unknown_source: "來源尚未核實",
};
const ALLOWED_USE = {test: "安排測試", retain_control: "保留對照", market_support: "支持本期方向", brand_fact: "引用品牌事實", operation: "核對操作"};

function SourceField({ label, value }: { label: string; value: string | null }) {
  return <div className="min-w-0"><dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-1 text-[13px] [overflow-wrap:anywhere]">{value ?? "尚未核實"}</dd></div>;
}

/** Presentation only: support, eligibility and counts are the server's qualification. */
export function LearningEvidenceCard({ evidence, onSource, compact = false, scopeLabel }: {
  evidence: LearningEvidence; onSource?: (evidence: LearningEvidence) => void; compact?: boolean; scopeLabel?: string;
}) {
  const tone: ChipTone = evidence.use_state === "usable" ? "ok" : evidence.use_state === "revalidation" ? "warn" : "neutral";
  return <article data-slot="learning-evidence" className={compact ? "min-w-0" : "min-w-0 border-t border-border py-4 first:border-t-0"}>
    {!compact && <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
      <Chip tone={tone}>{USE_LABEL[evidence.use_state]}</Chip>
      <span className="text-xs text-muted-foreground [overflow-wrap:anywhere]">{evidence.support_label}</span>
    </div>}
    <p className={compact ? "text-[13px] font-semibold leading-6 [overflow-wrap:anywhere]" : "text-[13px] leading-7 [overflow-wrap:anywhere]"}>{evidence.display_text}</p>
    {compact && scopeLabel && <p className="mt-1 text-xs text-muted-foreground [overflow-wrap:anywhere]">{scopeLabel}</p>}
    {compact && <p className="mt-1 text-xs text-muted-foreground [overflow-wrap:anywhere]">{evidence.support_label}</p>}
    {Array.from(new Set(evidence.reason_labels)).filter(reason => !compact || reason !== evidence.support_label).map((reason, i) => <p key={i} className="mt-1 text-xs text-muted-foreground [overflow-wrap:anywhere]">{reason}</p>)}
    {onSource && <Button variant="ghost" size="sm" className="mt-2" onClick={() => onSource(evidence)}>查看來源與限制 →</Button>}
  </article>;
}

export function LearningEvidenceState({ evidence }: {evidence: LearningEvidence}) {
  return <Chip tone={evidence.use_state === "usable" ? "ok" : evidence.use_state === "revalidation" ? "warn" : "neutral"}>{USE_LABEL[evidence.use_state]}</Chip>;
}

export function LearningEvidenceOrigin({ evidence }: {evidence: LearningEvidence}) {
  return <Chip tone={evidence.provenance === "simulation" ? "accent" : "neutral"}>{ORIGIN_LABEL[evidence.provenance]}</Chip>;
}

/** Shared source drilldown for strategy, Library and revalidation; null stays unknown. */
export function LearningEvidenceSource({ evidence, audienceLabel }: { evidence: LearningEvidence; audienceLabel?: string | null }) {
  return <div data-slot="learning-source" className="flex min-w-0 flex-col gap-5">
    <div className="flex flex-wrap gap-2"><Chip>{ORIGIN_LABEL[evidence.provenance]}</Chip><Chip>{USE_LABEL[evidence.use_state]}</Chip></div>
    <div><h3 className="text-base font-semibold [overflow-wrap:anywhere]">{evidence.display_text}</h3>
      <p className="mt-1 text-sm text-muted-foreground">{evidence.support_label}</p></div>
    <dl className="grid grid-cols-2 gap-x-5 gap-y-4 text-[13px]">
      <div><dt className="text-xs text-muted-foreground">來源活動</dt><dd className="mt-1 [overflow-wrap:anywhere]">{evidence.sources.map((source, i) => <p key={i}>{source.label ?? "來源名稱尚未提供"}</p>)}</dd></div>
      <div><dt className="text-xs text-muted-foreground">觀察期間</dt><dd className="mt-1 [overflow-wrap:anywhere]">{evidence.sources.map((source, i) => <p key={i}>{formatDay(source.period.start, "ymd") || "起日未知"} 至 {formatDay(source.period.end, "ymd") || "迄日未知"}</p>)}</dd></div>
      <div><dt className="text-xs text-muted-foreground">適用商品</dt><dd className="mt-1 [overflow-wrap:anywhere]">{evidence.scope.product_label ?? "商品尚未核實"}</dd></div>
      <div><dt className="text-xs text-muted-foreground">受眾</dt><dd className="mt-1 [overflow-wrap:anywhere]">{audienceLabel ?? "受眾名稱尚未提供"}</dd></div>
      <div><dt className="text-xs text-muted-foreground">成果樣本</dt><dd className="numeric mt-1">{evidence.sample.result_events === null ? "樣本尚未完整核實" : `${formatAmount(evidence.sample.result_events)} 筆`}</dd></div>
      <div><dt className="text-xs text-muted-foreground">當時每筆成本</dt><dd className="mt-1">來源未提供，尚未核實</dd></div>
      <div><dt className="text-xs text-muted-foreground">獨立觀察</dt><dd className="numeric mt-1">{formatAmount(evidence.independent_count)} 次</dd></div>
      <div><dt className="text-xs text-muted-foreground">連續同向</dt><dd className="numeric mt-1">{formatAmount(evidence.same_direction_count)} 次</dd></div>
      <div><dt className="text-xs text-muted-foreground">反向觀察</dt><dd className="numeric mt-1">{formatAmount(evidence.contrary_count)} 次</dd></div>
    </dl>
    <section><h4 className="text-sm font-semibold">目前如何使用</h4>
      <ul className="mt-2 space-y-1 text-[13px]">{evidence.reason_labels.map((reason, i) => <li key={i}>{reason}</li>)}</ul>
      <p className="mt-2 text-xs text-muted-foreground">觀察不能證明哪個賣點造成結果，也不是效果保證。</p>
      <p className="mt-2 text-[13px]">{evidence.allowed_uses.length > 0 ? `可用於：${evidence.allowed_uses.map((use) => ALLOWED_USE[use]).join("、")}` : "本期沒有已核准的使用方式，保留來源供查核。"}</p>
    </section>
    <Disclosure label="完整來源與限制">
      <ul className="space-y-3 text-[13px]">{evidence.sources.map((source, i) => <li key={i} className="[overflow-wrap:anywhere]">
        <p className="font-medium">{source.label ?? "來源名稱尚未提供"}</p>
        <p className="mt-1 text-xs text-muted-foreground">{formatDay(source.period.start, "ymd") || "起日未知"} 至 {formatDay(source.period.end, "ymd") || "迄日未知"}</p>
        <dl className="mt-2 grid grid-cols-2 gap-3"><SourceField label="來源類型" value={source.kind ? SOURCE_KIND[source.kind] : null} /><SourceField label="來源識別" value={source.id} /><SourceField label="來源版本" value={source.version} /></dl>
      </li>)}</ul>
      <dl className="mt-4 grid grid-cols-2 gap-4">
        <SourceField label="成果類型（來源值）" value={evidence.scope.result_kind} />
        <SourceField label="幣別" value={evidence.scope.currency} />
        <SourceField label="成果歸因方式（來源值）" value={evidence.scope.attribution} />
        <SourceField label="優惠條件" value={evidence.conditions.offer_key === "none" ? "不使用優惠" : evidence.conditions.offer_key} />
        <SourceField label="優惠版本" value={evidence.conditions.offer_version} />
        <SourceField label="價格版本" value={evidence.conditions.price_version} />
        <SourceField label="素材版本" value={evidence.conditions.material_version} />
        <SourceField label="投放設定版本" value={evidence.conditions.target_version} />
        <SourceField label="有效期限" value={formatDay(evidence.conditions.valid_until, "ymd") || null} />
      </dl>
      <p className="mt-3 text-xs text-muted-foreground">版本像資料的指紋，用來核對是否仍是同一份條件；期限未核實不代表永久有效。</p>
      <section className="mt-4"><h4 className="text-sm font-semibold">來源限制</h4>
        {evidence.limits.length > 0 ? <ul className="mt-2 space-y-2 text-xs text-muted-foreground">{evidence.limits.map((limit, i) => <li key={i} className="[overflow-wrap:anywhere]">{LIMIT_LABEL[limit] ?? "來源附加限制"} <code>({limit})</code></li>)}</ul> : <p className="mt-2 text-xs text-muted-foreground">來源未另列限制，不代表沒有不確定性。</p>}
      </section>
    </Disclosure>
  </div>;
}
