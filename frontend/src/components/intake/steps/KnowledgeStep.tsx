import { useState } from "react";
import type { IntakeDraft } from "@/lib/intakeApi";
import { HandoffStep } from "./HandoffStep";
import { PasteStep } from "./PasteStep";
import { QuestionStep } from "./QuestionStep";

/** 精靈第 4 步「品牌知識」（F05-I07：這張票只做「搬」——把原本各自佔一個大步驟的
 * 引導問答／交接包／貼回三個既有元件，依序放進同一個步驟裡，用內部 `phase` 取代原本
 * 「往下一個大步驟走」的 `onNext`；三個子元件本身這張票一個字都不准改。 */
export function KnowledgeStep({
  brandId,
  draft,
  onRefresh,
}: {
  brandId: string;
  draft: IntakeDraft;
  onRefresh: () => void;
}) {
  const [phase, setPhase] = useState<"question" | "handoff" | "paste">(() => {
    if (!draft.qa_done) return "question";
    if (!draft.handoff_generated) return "handoff";
    return "paste";
  });

  switch (phase) {
    case "question":
      return (
        <QuestionStep
          key={draft.question_index}
          brandId={brandId}
          draft={draft}
          onRefresh={onRefresh}
          onNext={() => setPhase("handoff")}
        />
      );
    case "handoff":
      return <HandoffStep brandId={brandId} draft={draft} onRefresh={onRefresh} onNext={() => setPhase("paste")} />;
    case "paste":
    default:
      return <PasteStep brandId={brandId} draft={draft} onRefresh={onRefresh} />;
  }
}
