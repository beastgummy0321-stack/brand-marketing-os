import { useState } from "react";
import type { IntakeDraft } from "@/lib/intakeApi";
import { COST_RESEARCH_STANDARD, fetchResearchStatus, startResearch } from "@/lib/intakeApi";
import { IntakeJobRow } from "../shared/IntakeJobRow";
import { LimitCard } from "../shared/LimitCard";
import { useIntakeJob } from "../useIntakeJob";
import { HandoffStep } from "./HandoffStep";
import { PasteStep } from "./PasteStep";
import { QuestionStep } from "./QuestionStep";

type Phase = "question" | "research" | "handoff" | "paste";

/** 精靈第 4 步「品牌知識」：問答 → 系統自己跑研究（預設）→ 真相卡；「改用外部 AI 跑
 * （進階）」摺疊起既有的交接包＋貼回流程（F05-I09）。三個既有子元件
 * （QuestionStep／HandoffStep／PasteStep）這張票一個字都不改，只加一個新的中間階段。 */
export function KnowledgeStep({
  brandId,
  draft,
  onRefresh,
}: {
  brandId: string;
  draft: IntakeDraft;
  onRefresh: () => void;
}) {
  // 舊草稿已經生成過交接包或已經貼過東西，代表原本就走進階路徑——續接維持在那條路，
  // 不要把人拉回一個看起來像「重新開始」的按鈕（F05 decisions 第 15 條「中繼狀態」精神）。
  const [phase, setPhase] = useState<Phase>(() => {
    if (!draft.qa_done) return "question";
    if (draft.paste_raw) return "paste";
    if (draft.handoff_generated) return "handoff";
    return "research";
  });

  switch (phase) {
    case "question":
      return (
        <QuestionStep
          key={draft.question_index}
          brandId={brandId}
          draft={draft}
          onRefresh={onRefresh}
          onNext={() => setPhase("research")}
        />
      );
    case "research":
      return (
        <ResearchPhase
          brandId={brandId}
          onDone={() => {
            onRefresh();
            setPhase("paste");
          }}
          onAdvanced={() => setPhase("handoff")}
        />
      );
    case "handoff":
      return <HandoffStep brandId={brandId} draft={draft} onRefresh={onRefresh} onNext={() => setPhase("paste")} />;
    case "paste":
    default:
      return <PasteStep brandId={brandId} draft={draft} onRefresh={onRefresh} />;
  }
}

function ResearchPhase({
  brandId,
  onDone,
  onAdvanced,
}: {
  brandId: string;
  onDone: () => void;
  onAdvanced: () => void;
}) {
  const { job, limitBlock, raising, retry, raise } = useIntakeJob(
    brandId,
    "research",
    false, // 使用者按鈕觸發，不自動開始（花系統的錢）
    () => startResearch(brandId),
    () => fetchResearchStatus(brandId),
    onDone,
  );

  if (limitBlock) {
    return <LimitCard block={limitBlock} raising={raising} onRaise={() => void raise()} onSkipRemaining={onAdvanced} />;
  }

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-border bg-card p-6 shadow-[var(--shadow-card)]">
      <div>
        <h2 className="font-display text-lg text-foreground">整理品牌知識</h2>
        <p className="text-sm text-muted-foreground">
          系統會用你填的網址與剛才的回答整理，大約 1 到 3 分鐘，花的是系統的錢（約 US${COST_RESEARCH_STANDARD.toFixed(2)}）。
        </p>
      </div>

      {job ? (
        <IntakeJobRow
          job={job}
          runningLabel="正在整理品牌知識"
          actions={[
            { label: "再試一次", onClick: () => void retry() },
            { label: "先看已存的內容，自己修", onClick: onDone },
            { label: "改用外部 AI 跑（進階）", onClick: onAdvanced },
          ]}
        />
      ) : (
        <button
          type="button"
          onClick={() => void retry()}
          className="self-start rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
        >
          開始整理品牌知識
        </button>
      )}

      <button type="button" onClick={onAdvanced} className="self-start text-sm text-primary hover:underline">
        改用外部 AI 跑（進階）
      </button>
    </div>
  );
}
