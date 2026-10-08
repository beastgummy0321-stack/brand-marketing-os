import type { StrategyBasis, StrategyDecision } from "@/lib/adsStrategyTypes";
import { Button } from "@/components/layout/ui/button";
import { Chip, Disclosure, LearningEvidenceCard } from "../patterns";

import { usedEvidence, unavailableCitations, unusedEvidence } from "./evidenceProjection";
import { ContinuationEvidence } from "./StrategyQualification";

export function StrategyEvidence({ basis, decision, onBasis }: {
  basis: StrategyBasis | undefined; decision?: StrategyDecision; onBasis: () => void;
}) {
  const used = usedEvidence(basis, decision);
  const unused = unusedEvidence(basis, decision);
  const unavailable = unavailableCitations(basis, decision);
  const verified = Boolean(basis?.evidence_context);
  const cold = verified && basis!.evidence_context.eligible_count === 0;
  return <section data-slot="strategy-evidence" className="surface min-w-0 self-start">
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-[22px] py-[18px]">
      <h2 className="text-base font-semibold">為什麼這樣安排</h2>
      <Button variant="ghost" size="sm" disabledReason={!basis ? "策略依據尚未提供" : undefined} onClick={onBasis}>查看依據 →</Button>
    </div>
    <ContinuationEvidence source={decision?.facts?.continuation ?? basis?.planner_context?.continuation} />
    <div className="grid grid-cols-2 gap-x-[22px] px-[22px] py-1 min-[1101px]:grid-cols-1">
      {used.length > 0 ? used.map((row) => <div key={row.id}><LearningEvidenceCard evidence={row} />
        <p className="pb-3 text-xs text-muted-foreground">{row.allowed_uses.includes("market_support") ? "可作市場表現參考；仍未證明因果" : row.allowed_uses.includes("retain_control") ? "可沿用對照；未證明市場有效" : row.allowed_uses.includes("test") ? "僅供新測試；未證明市場有效" : "依已核實用途參考"}</p>
      </div>) :
        <div className="py-4"><Chip>{unavailable.length > 0 ? "引用條件需核對" : cold ? "尚無可用歷史" : verified ? "尚未列出可用引用" : "歷史適用性尚未核實"}</Chip>
          <p className="mt-2 text-[13px] leading-7">{unavailable.length > 0 ? "原提案已引用來源，但目前只能保留歷史或待核對；不能作為有效支持。" : cold ? "以已確認商品事實和顧客群提出方向。" : verified ? "這份提案未列出可用的歷史引用。" : "尚未提供完整依據；不能把未讀到的資料當成沒有歷史。"}</p>
          <p className="mt-1 text-xs text-muted-foreground">新提案仍待驗證，不代表已證明有效。</p></div>}
      {basis?.evidence_context?.omitted ? <p className="py-2 text-xs text-muted-foreground">另有 {basis.evidence_context.omitted} 條紀錄未在此列出；請到品牌學習查看。</p> : null}
    </div>
    {unavailable.length > 0 && <Disclosure label="已引用但目前不可用">
      {unavailable.map(row => <LearningEvidenceCard key={row.id} evidence={row} />)}
    </Disclosure>}
    <Disclosure label="未用於提案的資料">
      {unused.length > 0 ? unused.map((row) => <LearningEvidenceCard key={row.id} evidence={row} />) :
        <p className="text-[13px] text-muted-foreground">{verified ? "沒有另列未採用的紀錄；未知資料不補成有效證據。" : "資料尚未提供；未採用紀錄也尚未核實。"}</p>}
    </Disclosure>
  </section>;
}
