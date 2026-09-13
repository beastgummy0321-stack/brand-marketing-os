import { useState } from "react";
import type { IntakeDraft } from "@/lib/intakeApi";
import { answerQuestion, fetchQuestionStatus, skipQuestionRemaining, skipRemainingAi, startQuestion } from "@/lib/intakeApi";
import { IntakeJobRow } from "../shared/IntakeJobRow";
import { LimitCard } from "../shared/LimitCard";
import { useIntakeJob } from "../useIntakeJob";

const MAX_QUESTIONS = 8;

/** 引導問答（契約 S4.25–S4.32）：進入這一步且目前沒有可回答的題目就自動出下一題。 */
export function QuestionStep({
  brandId,
  draft,
  onRefresh,
  onNext,
}: {
  brandId: string;
  draft: IntakeDraft;
  onRefresh: () => void;
  onNext: () => void;
}) {
  const { job, limitBlock, raising, retry, raise } = useIntakeJob(
    brandId,
    "question",
    !draft.qa_done && draft.current_q === null,
    () => startQuestion(brandId),
    () => fetchQuestionStatus(brandId),
    onRefresh,
  );

  /** S4.74（超限攔截卡片）：放棄所有還沒跑的 AI 步驟，直接去交接包。 */
  async function handleSkipRemainingAi() {
    await skipRemainingAi(brandId);
    onRefresh();
  }

  /** S4.31（背景出題失敗列）：只放棄「還沒問完的問題」，不算全面棄權。 */
  async function handleSkipQuestionRemaining() {
    await skipQuestionRemaining(brandId);
    onRefresh();
  }

  if (limitBlock) {
    return <LimitCard block={limitBlock} raising={raising} onRaise={() => void raise()} onSkipRemaining={() => void handleSkipRemainingAi()} />;
  }

  if (draft.qa_done) {
    return (
      <div className="flex flex-col gap-3 rounded-lg border border-dashed border-border bg-card p-6 text-sm">
        <p className="font-medium text-foreground">沒有需要再問的問題了</p>
        <p className="text-muted-foreground">資料夠了，系統可以開始整理品牌知識。</p>
        <button
          type="button"
          onClick={onNext}
          className="self-start rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
        >
          開始整理品牌知識
        </button>
      </div>
    );
  }

  if (!draft.current_q) {
    if (!job) return <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">準備出下一題…</div>;
    return (
      <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-6 shadow-[var(--shadow-card)]">
        <IntakeJobRow
          job={job}
          runningLabel="AI 正在出題"
          actions={[
            { label: "再試一次（預估 US$0.10）", onClick: () => void retry() },
            { label: "跳過這一題", onClick: () => void handleAnswer(brandId, "skip", "", onRefresh) },
            { label: "不問了，直接開始整理", onClick: () => void handleSkipQuestionRemaining() },
            { label: "前往設定頁", onClick: () => window.location.assign("/app/settings") },
          ]}
        />
      </div>
    );
  }

  return (
    <QuestionForm
      brandId={brandId}
      questionIndex={draft.question_index}
      question={draft.current_q}
      onRefresh={onRefresh}
    />
  );
}

async function handleAnswer(brandId: string, choice: string, note: string, onRefresh: () => void) {
  await answerQuestion(brandId, { choice, note });
  onRefresh();
}

function QuestionForm({
  brandId,
  questionIndex,
  question,
  onRefresh,
}: {
  brandId: string;
  questionIndex: number;
  question: NonNullable<IntakeDraft["current_q"]>;
  onRefresh: () => void;
}) {
  const [choice, setChoice] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit() {
    if (!choice) return;
    if (choice === "other" && !note.trim()) {
      setError("你選了「我自己說」，請在補充欄寫一句你的想法。");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await answerQuestion(brandId, { choice, note: note.trim() });
      onRefresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "送出失敗，請稍後再試。");
    } finally {
      setSaving(false);
    }
  }

  async function skipThis() {
    setSaving(true);
    try {
      await handleAnswer(brandId, "skip", "", onRefresh);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-border bg-card p-6 shadow-[var(--shadow-card)]">
      <h2 className="font-display text-lg text-foreground">
        第 {questionIndex + 1} 題（最多 {MAX_QUESTIONS} 題，通常更早結束）
      </h2>
      <p className="text-sm text-foreground">{question.question}</p>

      <div className="flex flex-col gap-2">
        {dedupeChoiceOptions(question).map((opt) => (
          <ChoiceOption
            key={opt.key}
            selected={choice === opt.key}
            onSelect={() => setChoice(opt.key)}
            label={opt.label}
            desc={opt.desc}
            badge={opt.badge}
          />
        ))}
        <ChoiceOption selected={choice === "other"} onSelect={() => setChoice("other")} label="以上都不是，我自己說" desc="" />
      </div>

      {choice === "other" && (
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">補充說明</span>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={2}
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
        </label>
      )}

      {error && <p className="text-sm text-danger">{error}</p>}

      <div className="flex gap-2">
        <button
          type="button"
          disabled={saving || !choice}
          onClick={() => void submit()}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saving ? "處理中…" : "這題答完，下一題"}
        </button>
        <button
          type="button"
          disabled={saving}
          onClick={() => void skipThis()}
          className="rounded-md border border-border px-4 py-2 text-sm font-medium text-foreground hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          跳過這一題
        </button>
      </div>
    </div>
  );
}

/** RC-H：AI 建議與某個分支選項一字不差時、或分支之間彼此重複時只渲染一次
 * （V-2／V 站 1 演練實測抓到的重複選項），建議只保留成旁邊的小標籤。 */
function dedupeChoiceOptions(
  question: NonNullable<IntakeDraft["current_q"]>,
): { key: string; label: string; desc: string; badge?: string }[] {
  const options: { key: string; label: string; desc: string; badge?: string }[] = [];
  const seen = new Set<string>();
  function push(key: string, label: string, desc: string, badge?: string) {
    const sig = label.trim();
    if (seen.has(sig)) return;
    seen.add(sig);
    options.push({ key, label, desc, badge });
  }
  push("suggested", question.suggested.label, question.suggested.desc, "AI 建議");
  question.branches.forEach((b, i) => push(`branch_${i}`, b.label, b.desc));
  return options;
}

function ChoiceOption({
  selected,
  onSelect,
  label,
  desc,
  badge,
}: {
  selected: boolean;
  onSelect: () => void;
  label: string;
  desc: string;
  badge?: string;
}) {
  return (
    <label className={`flex cursor-pointer flex-col gap-0.5 rounded-md border p-3 text-sm ${selected ? "border-primary bg-primary/5" : "border-border"}`}>
      <div className="flex items-center gap-2">
        <input type="radio" checked={selected} onChange={onSelect} />
        <span className="font-medium text-foreground">{label}</span>
        {badge && <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs text-primary">{badge}</span>}
      </div>
      {desc && <p className="pl-6 text-xs text-muted-foreground">{desc}</p>}
    </label>
  );
}
