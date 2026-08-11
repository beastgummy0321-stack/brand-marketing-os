import { useEffect, useState } from "react";
import type { IntakeDraft } from "@/lib/intakeApi";
import { DEPTH_OPTIONS, fetchOperatorCard, generateHandoff } from "@/lib/intakeApi";

/** 交接包（契約 S4.33–S4.45）：depth 二選一 → 產生 Prompt → 複製 → 操作卡（Claude／
 * ChatGPT）子畫面，不佔獨立步驟條位置。 */
export function HandoffStep({
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
  const [depth, setDepth] = useState<"standard" | "deep">(draft.handoff_depth ?? "standard");
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const [provider, setProvider] = useState<"claude" | "chatgpt" | null>(null);

  async function handleGenerate() {
    setGenerating(true);
    setError(null);
    try {
      await generateHandoff(brandId, depth);
      onRefresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "產生失敗，請稍後再試。");
    } finally {
      setGenerating(false);
    }
  }

  async function handleCopy() {
    if (!draft.handoff_prompt) return;
    try {
      await navigator.clipboard.writeText(draft.handoff_prompt);
      setCopyState("copied");
    } catch {
      setCopyState("failed");
    }
  }

  if (provider) {
    return <OperatorCardView brandId={brandId} provider={provider} onBack={() => setProvider(null)} onNext={onNext} />;
  }

  return (
    <div className="flex flex-col gap-5 rounded-lg border border-border bg-card p-6 shadow-[var(--shadow-card)]">
      <div>
        <h2 className="font-display text-lg text-foreground">把調研包丟給外部 AI</h2>
        <p className="text-sm text-muted-foreground">這一步不花系統的錢——跑的是你自己的 Claude 或 ChatGPT 額度。</p>
      </div>

      {draft.created_product_names.length === 0 && (
        <div className="rounded-md border border-dashed border-border p-3 text-sm text-muted-foreground">
          交接包會告訴外部 AI「適用範圍只能填『整個品牌』」，因為這個品牌目前還沒有任何產品。
        </div>
      )}

      <div className="flex flex-col gap-2">
        {DEPTH_OPTIONS.map((opt) => (
          <label
            key={opt.value}
            className={`flex cursor-pointer flex-col gap-0.5 rounded-md border p-3 text-sm ${depth === opt.value ? "border-primary bg-primary/5" : "border-border"}`}
          >
            <div className="flex items-center gap-2">
              <input type="radio" checked={depth === opt.value} onChange={() => setDepth(opt.value)} />
              <span className="font-medium text-foreground">{opt.label}</span>
            </div>
            <p className="pl-6 text-xs text-muted-foreground">{opt.desc}</p>
          </label>
        ))}
      </div>

      {error && <p className="text-sm text-danger">{error}</p>}

      <button
        type="button"
        disabled={generating}
        onClick={() => void handleGenerate()}
        className="self-start rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {generating ? "處理中…" : draft.handoff_generated ? "換另一種深度重新產生" : "產生交接包"}
      </button>

      {draft.handoff_prompt && (
        <div className="flex flex-col gap-3">
          <div className="max-h-64 overflow-y-auto whitespace-pre-wrap rounded-md border border-border bg-muted/30 p-3 text-xs text-foreground">
            {draft.handoff_prompt}
          </div>
          <button
            type="button"
            onClick={() => void handleCopy()}
            className="self-start rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground hover:border-primary hover:text-primary"
          >
            {copyState === "copied" ? "已複製" : copyState === "failed" ? "沒複製到，點一下框內全選再 Ctrl+C" : "複製全部"}
          </button>

          {draft.photos.length > 0 && (
            <div className="rounded-md border border-border p-3 text-xs text-muted-foreground">
              <p className="mb-1 font-medium text-foreground">別忘了附上產品照</p>
              <ul className="flex flex-col gap-1">
                {draft.photos.map((p, i) => (
                  <li key={i}>
                    {p.name}（{p.size_mb.toFixed(1)}MB）
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div>
            <p className="mb-2 text-sm font-medium text-foreground">接下來到哪裡貼？</p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setProvider("claude")}
                className="rounded-md border border-border px-3 py-1.5 text-sm font-medium text-foreground hover:border-primary hover:text-primary"
              >
                在 Claude 怎麼跑
              </button>
              <button
                type="button"
                onClick={() => setProvider("chatgpt")}
                className="rounded-md border border-border px-3 py-1.5 text-sm font-medium text-foreground hover:border-primary hover:text-primary"
              >
                在 ChatGPT 怎麼跑
              </button>
            </div>
          </div>

          <button
            type="button"
            onClick={onNext}
            className="self-start rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
          >
            我跑完了，去貼回來
          </button>
        </div>
      )}
    </div>
  );
}

function OperatorCardView({
  brandId,
  provider,
  onBack,
  onNext,
}: {
  brandId: string;
  provider: "claude" | "chatgpt";
  onBack: () => void;
  onNext: () => void;
}) {
  const [card, setCard] = useState<{ title: string; steps: string[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fallbackOpen, setFallbackOpen] = useState(false);

  useEffect(() => {
    fetchOperatorCard(brandId, provider)
      .then(setCard)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "讀取失敗，請稍後再試。"));
  }, [brandId, provider]);

  if (error) return <p className="text-sm text-danger">{error}</p>;
  if (!card) return <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">讀取中…</div>;

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-border bg-card p-6 shadow-[var(--shadow-card)]">
      <h2 className="font-display text-lg text-foreground">{card.title}</h2>
      <div className="rounded-md border border-warning/40 bg-warning/5 p-3 text-sm text-foreground">一個品牌開一個全新對話。</div>
      <ol className="flex list-decimal flex-col gap-2 pl-5 text-sm text-foreground">
        {card.steps.map((s, i) => (
          <li key={i}>{s}</li>
        ))}
      </ol>

      <button type="button" onClick={() => setFallbackOpen((v) => !v)} className="self-start text-sm text-primary hover:underline">
        它如果沒有照格式輸出怎麼辦？
      </button>
      {fallbackOpen && (
        <p className="text-sm text-muted-foreground">直接把它給你的東西貼回來就好。系統會先檢查，格式不對會告訴你哪幾列有問題，也可以讓系統花一點錢幫你整理。</p>
      )}

      <div className="flex gap-2">
        <button
          type="button"
          onClick={onNext}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
        >
          我跑完了，去貼回來
        </button>
        <button type="button" onClick={onBack} className="text-sm text-muted-foreground hover:underline">
          回到交接包
        </button>
      </div>
    </div>
  );
}
