import { useEffect, useState, type ReactNode } from "react";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import {
  deactivateLearning,
  deactivateRule,
  fetchLearnings,
  reconfirmRule,
  type LearningSections,
} from "@/lib/learningsApi";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: LearningSections };

export function LearningsPage({ brandId }: { brandId: string }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [savingId, setSavingId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load() {
    setState({ status: "loading" });
    fetchLearnings(brandId)
      .then((data) => setState({ status: "ready", data }))
      .catch((cause: unknown) => {
        setState({ status: "error", message: cause instanceof Error ? cause.message : "讀取失敗，請稍後再試。" });
      });
  }

  useEffect(load, [brandId]);

  async function handleAction(id: string, action: () => Promise<{ message: string }>) {
    setSavingId(id);
    setMessage(null);
    setError(null);
    try {
      const result = await action();
      setMessage(result.message);
      load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "處理失敗，請稍後再試。");
    } finally {
      setSavingId(null);
    }
  }

  let content: ReactNode;
  if (state.status === "loading") {
    content = <div className="flex flex-col gap-3">{Array.from({ length: 7 }, (_, index) => <Skeleton key={index} className="h-20" />)}</div>;
  } else if (state.status === "error") {
    content = <EmptyState title="讀取失敗" description={state.message} actionLabel="重新載入" onAction={load} />;
  } else {
    const data = state.data;
    content = (
      <div className="flex flex-col gap-6">
        <Section title={`已確認的學習（${data.learnings.length}）`}>
          {data.learnings.map((entry) => (
            <Row key={entry.id}>
              <div><p>{entry.learning_text}</p><p className="mt-1 text-xs text-muted-foreground">{entry.meta_line}</p></div>
              <ActionButton
                saving={savingId === entry.id}
                onClick={() => {
                  if (window.confirm("確定這條學習不適用了？下架後不會再進入生成內容的依據。")) {
                    void handleAction(entry.id, () => deactivateLearning(brandId, entry.id));
                  }
                }}
              >這條不適用了</ActionButton>
            </Row>
          ))}
          <NoneWhen empty={data.learnings.length === 0} />
        </Section>

        <Section title={`生效中的禁令（${data.active_bans.length}）`}>
          {data.active_bans.map((ban) => (
            <Row key={ban.id}>
              <p>{ban.proposed_rule_text}</p>
              <ActionButton
                saving={savingId === ban.promoted_rule_id}
                onClick={() => {
                  if (window.confirm("確定這條禁令不適用了？下架後不會再避開這個方向。")) {
                    void handleAction(ban.promoted_rule_id, () => deactivateRule(brandId, ban.promoted_rule_id));
                  }
                }}
              >這條不適用了</ActionButton>
            </Row>
          ))}
          <NoneWhen empty={data.active_bans.length === 0} />
        </Section>

        <Section title={`逾期待確認的規則（${data.pending_reconfirm_rules.length}）`}>
          {data.pending_reconfirm_rules.map((rule) => (
            <Row key={rule.id}>
              <div><p>{rule.content}</p>{rule.confirmed_at && <p className="mt-1 text-xs text-muted-foreground">最近確認時間：{rule.confirmed_at.slice(0, 10)}</p>}</div>
              <ActionButton saving={savingId === rule.id} onClick={() => void handleAction(rule.id, () => reconfirmRule(brandId, rule.id))}>還是適用，續用</ActionButton>
            </Row>
          ))}
          <NoneWhen empty={data.pending_reconfirm_rules.length === 0} />
        </Section>

        <Section title={`還沒處理的候選（${data.pending_cards.length}）`}>
          {data.pending_cards.map((card) => <ReadOnlyRow key={card.id}>{card.proposed_rule_text}</ReadOnlyRow>)}
          <NoneWhen empty={data.pending_cards.length === 0} />
        </Section>

        <Section title={`觀察中的訊號（${data.observing_signals.length}）`}>
          {data.observing_signals.map((signal) => <ReadOnlyRow key={`${signal.axis_label}-${signal.value_label}`}>{signal.axis_label}：{signal.value_label}</ReadOnlyRow>)}
          <NoneWhen empty={data.observing_signals.length === 0} />
        </Section>

        <Section title={`待驗證的假說（${data.pending_hypotheses.length}）`}>
          {data.pending_hypotheses.map((hypothesis) => <ReadOnlyRow key={hypothesis.id}>{hypothesis.statement} <span className="ml-2 rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">{hypothesis.status_label}</span></ReadOnlyRow>)}
          <NoneWhen empty={data.pending_hypotheses.length === 0} />
        </Section>

        <Section title={`這次沒進 AI 依據的規則（${data.overflow_rules.length}）`}>
          {data.overflow_rules.map((rule) => <ReadOnlyRow key={rule.id}>{rule.content}</ReadOnlyRow>)}
          {data.overflow_rules.length > 0 && <p className="text-sm text-muted-foreground">超過一次能放的上限，下期優先。</p>}
          <NoneWhen empty={data.overflow_rules.length === 0} />
        </Section>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <Breadcrumb items={[{ label: "跨品牌總覽", href: "/" }, { label: "累積智慧" }]} />
      <div>
        <h1 className="font-display text-2xl text-foreground">累積智慧</h1>
        <p className="mt-1 text-sm text-muted-foreground">系統從每一期學到的事。這裡的內容會被寫進 AI 的判斷依據，不適用的可以下架。</p>
      </div>
      {message && <p className="rounded-md bg-success/10 px-3 py-2 text-sm text-foreground">{message}</p>}
      {error && <p className="rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">{error}</p>}
      {content}
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return <section><h2 className="mb-2 text-base font-medium text-foreground">{title}</h2><div className="rounded-lg border border-border bg-card shadow-[var(--shadow-card)]">{children}</div></section>;
}

function Row({ children }: { children: ReactNode }) {
  return <div className="flex items-start justify-between gap-4 border-b border-border p-4 last:border-b-0">{children}</div>;
}

function ReadOnlyRow({ children }: { children: ReactNode }) {
  return <div className="border-b border-border p-4 text-sm text-foreground last:border-b-0">{children}</div>;
}

function NoneWhen({ empty }: { empty: boolean }) {
  return empty ? <p className="p-4 text-sm text-muted-foreground">目前沒有</p> : null;
}

function ActionButton({ saving, onClick, children }: { saving: boolean; onClick: () => void; children: ReactNode }) {
  return <button type="button" disabled={saving} onClick={onClick} className="shrink-0 rounded-md border border-border px-3 py-1.5 text-sm font-medium text-foreground hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-60">{saving ? "處理中…" : children}</button>;
}
