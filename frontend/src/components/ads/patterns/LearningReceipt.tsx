import {useState} from "react";
import type {LearningEvidence} from "@/lib/adsLearningEvidence";
import {Button} from "@/components/layout/ui/button";
import {SidePanel} from "@/components/layout/SidePanel";
import {Chip, formatAmount} from "./Chip";
import {LearningEvidenceOrigin, LearningEvidenceSource, LearningEvidenceState} from "./LearningEvidence";

/** A recorded action and a qualified observation are separate readings. */
export function LearningReceipt({evidence, recorded, comparative = false}: {
  evidence: LearningEvidence | null; recorded: boolean; comparative?: boolean;
}) {
  const [sourceOpen, setSourceOpen] = useState(false);
  const sourceTitle = comparative ? "比較紀錄的來源與限制" : "暫停觀察的來源與限制";
  const title = recorded
    ? comparative ? "已保留這次比較紀錄" : "已記錄這次暫停觀察"
    : comparative ? "比較紀錄尚未核實" : "暫停操作尚未留紀錄";
  const fallback = recorded ? "本次操作已留紀錄；來源與適用性尚未核實" : "本次操作尚未留紀錄；來源與適用性尚未核實";
  return <section data-slot="learning-receipt" className="min-w-0 w-full max-w-[920px] rounded-xl border border-dashed border-border bg-card">
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-[22px] py-[18px]">
      <h2 className="text-[15px] font-semibold">{title}</h2>
      <Chip tone="warn">{evidence?.support_label ?? "來源尚未核實"}</Chip>
    </div>
    <div className="px-[22px] py-5">
      <h3 className="text-base font-semibold [overflow-wrap:anywhere]">{evidence?.display_text ?? fallback}</h3>
      {evidence?.reason_labels.map((reason, i) => <p key={i} className="mt-2 text-[13px] text-muted-foreground [overflow-wrap:anywhere]">{reason}</p>)}
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        {evidence && <><LearningEvidenceOrigin evidence={evidence}/><LearningEvidenceState evidence={evidence}/></>}
        <span className="[overflow-wrap:anywhere]">{evidence?.scope.product_label ?? (evidence?.scope.product_id ? "商品名稱尚未提供" : "商品範圍尚未核實")}</span>
        <span>{recorded ? "本次操作已留紀錄" : "本次操作尚未留紀錄"}</span>
      </div>
      {evidence && <p className="numeric mt-2 text-xs text-muted-foreground">獨立觀察 {formatAmount(evidence.independent_count)} 次 · 連續同向 {formatAmount(evidence.same_direction_count)} 次 · 反向 {formatAmount(evidence.contrary_count)} 次</p>}
      <Button variant="ghost" size="sm" className="mt-3" disabledReason={!evidence ? "本筆來源尚未提供，請重新讀取核對" : undefined} onClick={() => setSourceOpen(true)}>查看來源與限制 →</Button>
    </div>
    {sourceOpen && evidence && <SidePanel ariaLabel={sourceTitle} onClose={() => setSourceOpen(false)}>
      <h2 className="mb-5 text-lg font-semibold">{sourceTitle}</h2>
      <LearningEvidenceSource evidence={evidence}/>
      <Button variant="outline" className="mt-5" onClick={() => setSourceOpen(false)}>返回核對結果</Button>
    </SidePanel>}
  </section>;
}
