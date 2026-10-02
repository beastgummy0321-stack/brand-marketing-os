import { useId, useRef, useState, type ReactNode } from "react";
import { Button } from "@/components/layout/ui/button";
import type { CustomBlock, CustomProposal } from "@/lib/intakeOnboardingApi";
import { proposeCustom } from "@/lib/intakeOnboardingApi";
import type { ProductCustomBlock, ProductCustomProposal } from "@/lib/intakeProductApi";

/** 「自訂」 under every AI-judged onboarding block, prototype `custom(id, hint)` / `makeCus(id)` of
 * `.harness/scratch/prototype/f41-onboarding/index.html` (`.cusb`, `.cus`, `.mine`): a dashed button opens a
 * box with one sentence; 「讓 AI 整理」 sends it through `POST …/onboarding/custom` and the proposal goes back
 * to the caller by its `kind`:
 * - `value` (positioning, visual) → `onValue`: the caller fills its field and tags it `CustomMark`
 *   (「你自訂」, in place of the AI tag) while the field still holds that value;
 * - `option` (tone, brand_proof, policy, forbidden) → `onOption`: the caller adds it, checked, to its list or
 *   chips, marked `CustomMark` with its own × (the undo).
 * A result shows in ONE place, where it lives: this box lists nothing of its own. Nothing is saved here:
 * the step's 下一步 saves the field or list with everything else.
 * Product onboarding (F43) passes `propose` (its `POST …/products/{p}/onboarding/custom` call, blocks
 * `difference`, `group`, `pain`, `product_proof`, `claim`); without it the brand call above is used, which only
 * knows the brand blocks. */

/** A brand block (brand onboarding) or a product block (product onboarding, with `propose`). */
export type AnyCustomBlock = CustomBlock | ProductCustomBlock;
export type AnyCustomProposal = CustomProposal | ProductCustomProposal;
type OptionProposal = Extract<AnyCustomProposal, { kind: "option" }>;
/** The option a block's proposal carries (`{label}` for tone, `{fact_key, label, text}` for brand proof, …). */
export type CustomOption<B extends AnyCustomBlock> = Extract<OptionProposal, { block: B }>["option"];

const HINT = "覺得上面列的不對、不像你、或選項太少？直接用一句話描述，AI 幫你整理成選項";
const MAX_CHARS = 200;
/** F47-I03 (drill-10 乙 #5): why 「讓 AI 整理」 is off while the box is empty. */
const EMPTY_REASON = "先在上面寫一句話，AI 才有東西整理";

export function CustomEscape<B extends AnyCustomBlock>({ brandId, block, placeholder, propose, onValue, onOption }: {
  brandId: string;
  block: B;
  placeholder: string;
  /** One sentence -> the block's proposal; omitted = the brand call (`proposeCustom`, brand blocks only). */
  propose?: (text: string) => Promise<AnyCustomProposal>;
  onValue?: (value: string) => void;
  onOption?: (option: CustomOption<B>) => void;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** Bumped on cancel and on each request: a late answer to a cancelled request is dropped. */
  const ticket = useRef(0);
  const hintId = useId();
  /** The caller's latest callbacks: an answer that arrives after the caller re-rendered sees its current state. */
  const handlers = useRef({ onValue, onOption });
  handlers.current = { onValue, onOption };

  function close() {
    ticket.current += 1;
    setOpen(false);
    setText("");
    setBusy(false);
    setError(null);
  }

  async function organise() {
    const sentence = text.trim();
    if (!sentence || busy) return;
    const mine = ++ticket.current;
    setBusy(true);
    setError(null);
    try {
      const proposal = propose ? await propose(sentence) : await proposeCustom(brandId, block as CustomBlock, sentence);
      if (mine !== ticket.current) return;
      if (proposal.kind === "value") handlers.current.onValue?.(proposal.value);
      else handlers.current.onOption?.(proposal.option as CustomOption<B>);
      close();
    } catch (err) {
      if (mine !== ticket.current) return;
      setError(err instanceof Error ? err.message : "AI 整理不出來，換個說法再試一次");
      setBusy(false);
    }
  }

  return (
    <div data-slot="custom-escape" data-block={block}>
      {open ? (
        <div className="mt-2.5 rounded-[10px] border border-dashed border-grade-thin bg-accent/20 px-3 py-2.5">
          <div id={hintId} className="mb-1.5 text-[11.5px] text-muted-foreground">{HINT}</div>
          <textarea
            rows={2}
            aria-labelledby={hintId}
            className="w-full rounded-lg border border-input bg-card px-3 py-[9px] text-sm focus:border-primary focus:shadow-[0_0_0_3px_var(--color-accent)] focus:outline-none focus-visible:outline-none"
            placeholder={placeholder}
            maxLength={MAX_CHARS}
            value={text}
            disabled={busy}
            autoFocus
            onChange={(e) => setText(e.target.value)}
          />
          {error && <p role="alert" className="mt-1.5 text-xs text-danger">{error}</p>}
          <div className="mt-2 flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={!text.trim() || busy}
              disabledReason={!text.trim() && !busy ? EMPTY_REASON : undefined}
              aria-busy={busy}
              onClick={() => void organise()}
            >
              {busy && <span aria-hidden="true" className="size-3.5 animate-spin rounded-full border-2 border-chart-soft border-t-primary" />}
              讓 AI 整理
            </Button>
            <Button type="button" variant="ghost" size="sm" className="text-muted-foreground" onClick={close}>
              取消
            </Button>
          </div>
        </div>
      ) : (
        <div className="mt-2.5">
          <button
            type="button"
            className="rounded-full border border-dashed border-primary/50 bg-card px-[13px] py-[5px] text-[13px] font-semibold text-accent-foreground hover:border-primary hover:bg-accent/40"
            onClick={() => setOpen(true)}
          >
            ✎ 自訂：用自己的話說
          </button>
        </div>
      )}
    </div>
  );
}

/** The 「你自訂」 mark (prototype `.mine`) a block puts on a 自訂 result where it lives: next to a field it
 * filled (in place of the AI tag) or on the option it added. */
export function CustomMark({ children = "你自訂" }: { children?: ReactNode }) {
  return (
    <span data-slot="custom-mark" className="inline-flex shrink-0 items-center rounded bg-zone-ok px-1.5 py-px text-[11px] font-semibold whitespace-nowrap text-success-strong">
      {children}
    </span>
  );
}
