import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Pager } from "@/components/layout/Pager";
import {
  confirmTruthCard,
  fetchTruthCard,
  type TruthCard,
  type TruthCardBucket,
  type TruthCardItem,
} from "@/lib/intakeT2Api";
import { usePagination } from "@/lib/usePagination";
import { Badge } from "../shared/Badge";
import { TruthCardItemPanel } from "./TruthCardItemPanel";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "empty-confirming" }
  | { status: "ready"; data: TruthCard };

type Answer = { value?: string; decision?: "can_say" | "cannot_say" };

/** 真相卡（T2 條文 2.1–2.5）：已採用可掃視，只有價格與宣稱留給使用者作答。 */
export function TruthCardStep({
  brandId,
  knownProducts,
  onCompleted,
}: {
  brandId: string;
  knownProducts: string[];
  onCompleted: () => void;
}) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [answers, setAnswers] = useState<Record<string, Answer>>({});
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ item: TruthCardItem; bucket: TruthCardBucket; defaultTarget?: TruthCardBucket } | null>(null);
  const emptyConfirmStarted = useRef(false);

  function load() {
    emptyConfirmStarted.current = false;
    setState({ status: "loading" });
    setSaveError(null);
    fetchTruthCard(brandId)
      .then((data) => {
        setAnswers({});
        setState({ status: "ready", data });
      })
      .catch((err: unknown) => {
        setState({ status: "error", message: err instanceof Error ? err.message : "讀取真相卡失敗，請稍後再試。" });
      });
  }

  useEffect(load, [brandId]);

  const total = state.status === "ready" ? countItems(state.data) : 0;
  useEffect(() => {
    if (state.status !== "ready" || total !== 0 || emptyConfirmStarted.current) return;
    emptyConfirmStarted.current = true;
    setState({ status: "empty-confirming" });
    confirmTruthCard(brandId, {})
      .then(onCompleted)
      .catch((err: unknown) => {
        setState({ status: "error", message: err instanceof Error ? err.message : "完成建檔失敗，請再試一次。" });
      });
  }, [brandId, onCompleted, state.status, total]);

  const accepted = state.status === "ready" ? state.data.accepted : [];
  const acceptedPage = usePagination(accepted);
  const needs = state.status === "ready" ? state.data.needs_confirmation : [];
  const cannotSay = needs.filter((item) => item.answer_kind === "claim_permission" && answers[item.id]?.decision === "cannot_say");
  const visibleNeeds = needs.filter((item) => !cannotSay.includes(item));
  const forbidden = state.status === "ready" ? [...state.data.forbidden, ...cannotSay] : [];
  const missing = useMemo(
    () => needs.filter((item) => item.answer_kind && !answers[item.id]?.value && !answers[item.id]?.decision),
    [answers, needs],
  );

  async function submit() {
    if (missing.length > 0) return;
    setSaving(true);
    setSaveError(null);
    try {
      await confirmTruthCard(brandId, answers);
      onCompleted();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "這張卡暫時存不進去，請再試一次。");
    } finally {
      setSaving(false);
    }
  }

  if (state.status === "loading") {
    return <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">正在整理這次帶回來的內容…</div>;
  }
  if (state.status === "empty-confirming") {
    return <div className="rounded-lg border border-dashed border-border bg-card p-6 text-sm text-muted-foreground">這次沒有新條目，正在完成建檔…</div>;
  }
  if (state.status === "error") {
    return (
      <div className="flex flex-col gap-3 rounded-lg border border-danger/40 bg-danger/5 p-6 text-sm">
        <p className="font-medium text-danger">真相卡暫時讀不到</p>
        <p className="text-muted-foreground">{state.message}</p>
        <div><button type="button" onClick={load} className="rounded-md border border-border px-3 py-1.5 text-sm font-medium text-foreground hover:border-primary hover:text-primary">重新讀取</button></div>
      </div>
    );
  }

  const missingText = missing.length === 0 ? "已經答完了，可以完成建檔。" : "還缺：" + missing.map((item) => item.title).join("、") + "。答完就能按。";

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-border bg-card p-6 shadow-[var(--shadow-card)]">
      <div>
        <h2 className="font-display text-lg text-foreground">真相卡</h2>
        <p className="text-sm text-muted-foreground">先掃一眼已採用的內容；只有價格和能不能說的話需要你決定。</p>
      </div>

      <TruthGroup title={"已採用（" + accepted.length + " 條）"} tone="success" hint="這些會直接生效，之後隨時可回來改。">
        <div ref={acceptedPage.topRef} className="flex flex-col gap-2">
          {acceptedPage.pageItems.map((item) => <TruthRow key={item.id} item={item} onEdit={() => setEditing({ item, bucket: "accepted" })} />)}
        </div>
        <Pager page={acceptedPage.page} pageCount={acceptedPage.pageCount} totalCount={acceptedPage.totalCount} onChange={acceptedPage.goToPage} />
      </TruthGroup>

      <TruthGroup title={"等你確認（" + visibleNeeds.length + " 條）"} tone="warning" hint="只有商業數字和不能亂說的話會在這裡。">
        {visibleNeeds.length === 0 ? (
          <p className="text-sm text-muted-foreground">這一格已經沒有要補的內容。</p>
        ) : (
          <div className="flex flex-col gap-2">
            {visibleNeeds.map((item) => (
              <TruthAnswerRow
                key={item.id}
                item={item}
                answer={answers[item.id]}
                onAnswer={(answer) => setAnswers((prev) => ({ ...prev, [item.id]: answer }))}
                onEdit={() => setEditing({ item, bucket: "needs_confirmation" })}
              />
            ))}
          </div>
        )}
      </TruthGroup>

      <TruthGroup title={"禁止使用（" + forbidden.length + " 條）"} tone="danger" hint="這些不會拿去對外使用。">
        {forbidden.length === 0 ? <p className="text-sm text-muted-foreground">目前沒有禁止使用的內容。</p> : <div className="flex flex-col gap-2">{forbidden.map((item) => <TruthRow key={item.id} item={item} onEdit={() => setEditing(cannotSay.includes(item) ? { item, bucket: "needs_confirmation", defaultTarget: "forbidden" } : { item, bucket: "forbidden" })} />)}</div>}
      </TruthGroup>

      <div className="flex flex-col items-start gap-2">
        <button
          type="button"
          disabled={saving || missing.length > 0}
          onClick={() => void submit()}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saving ? "正在完成建檔…" : "✅ 這張卡正確，完成建檔"}
        </button>
        <p role="status" aria-live="polite" className="text-sm text-muted-foreground">{saving ? "正在落檔，請不要重複按。" : missingText}</p>
        {saveError && <p role="alert" className="text-sm text-danger">{saveError}</p>}
      </div>

      {editing && (
        <TruthCardItemPanel
          brandId={brandId}
          item={editing.item}
          initialBucket={editing.bucket}
          defaultTarget={editing.defaultTarget}
          knownProducts={knownProducts}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            load();
          }}
        />
      )}
    </div>
  );
}

function countItems(card: TruthCard) {
  return card.accepted.length + card.needs_confirmation.length + card.forbidden.length;
}

function TruthGroup({ title, tone, hint, children }: { title: string; tone: "success" | "warning" | "danger"; hint: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2 rounded-md border border-border p-3">
      <div className="flex flex-wrap items-center gap-2"><Badge tone={tone}>{title}</Badge><span className="text-xs text-muted-foreground">{hint}</span></div>
      {children}
    </section>
  );
}

function TruthRow({ item, onEdit }: { item: TruthCardItem; onEdit: () => void }) {
  return (
    <div className="flex items-start gap-3 rounded-md border border-border p-3 text-sm">
      <p className="min-w-0 flex-1 break-words text-foreground"><span className="font-medium">{item.kind}・{displayCategory(item.category)}</span>｜{item.title}{item.content ? "：" + item.content : ""}</p>
      <button type="button" onClick={onEdit} className="shrink-0 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground hover:border-primary hover:text-primary">改</button>
    </div>
  );
}

function TruthAnswerRow({ item, answer, onAnswer, onEdit }: { item: TruthCardItem; answer: Answer | undefined; onAnswer: (answer: Answer) => void; onEdit: () => void }) {
  if (item.answer_kind === "price") {
    return (
      <div className="flex flex-wrap items-center gap-3 rounded-md border border-border p-3 text-sm">
        <label className="min-w-48 flex-1 font-medium text-foreground">💰 {item.title}<input value={answer?.value ?? ""} onChange={(event) => onAnswer({ value: event.target.value })} aria-label={item.title + "的售價"} placeholder="例如 NT$ 480" className="mt-2 block w-full rounded-md border border-border px-3 py-2 text-sm text-foreground" /></label>
        <button type="button" onClick={onEdit} className="rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground hover:border-primary hover:text-primary">改</button>
      </div>
    );
  }
  if (item.answer_kind === "claim_permission") {
    return (
      <div className="flex flex-wrap items-center gap-3 rounded-md border border-border p-3 text-sm">
        <p className="min-w-48 flex-1 font-medium text-foreground">{item.title}可以講嗎？</p>
        <button type="button" onClick={() => onAnswer({ decision: "can_say" })} className={"rounded-md border px-3 py-1.5 text-xs font-medium " + (answer?.decision === "can_say" ? "border-primary bg-primary/10 text-primary" : "border-border text-foreground hover:border-primary hover:text-primary")}>可以</button>
        <button type="button" onClick={() => onAnswer({ decision: "cannot_say" })} className={"rounded-md border px-3 py-1.5 text-xs font-medium " + (answer?.decision === "cannot_say" ? "border-danger bg-danger/10 text-danger" : "border-border text-foreground hover:border-danger hover:text-danger")}>不能講</button>
        <button type="button" onClick={onEdit} className="rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground hover:border-primary hover:text-primary">改</button>
      </div>
    );
  }
  return <TruthRow item={item} onEdit={onEdit} />;
}

function displayCategory(category: string) {
  return category === "受眾" ? "要傳給誰" : category;
}
