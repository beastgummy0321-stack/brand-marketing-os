import { useId, useRef, useState } from "react";
import { Button } from "@/components/layout/ui/button";
import type { CustomBlock, CustomProposal } from "@/lib/intakeOnboardingApi";
import { proposeCustom } from "@/lib/intakeOnboardingApi";

/** 「自訂」 under every AI-judged onboarding block, prototype `custom(id, hint)` / `makeCus(id)` of
 * `.harness/scratch/prototype/f41-onboarding/index.html` (`.cusb`, `.cus`, `.it` + `.mine`): a dashed
 * button opens a box with one sentence; 「讓 AI 整理」 sends it through `POST …/onboarding/custom` and
 * the proposal goes back to the caller by its `kind`:
 * - `value` (positioning, visual) → `onValue`: the caller replaces its field;
 * - `option` (tone, brand_proof, policy, forbidden) → `onOption`: the caller adds it, checked, to its list.
 * Each result is listed as 「你自訂」; its × calls the undo the caller returned. Nothing is saved here:
 * the step's 下一步 saves the field or list with everything else. */

type OptionProposal = Extract<CustomProposal, { kind: "option" }>;
/** The option a block's proposal carries (`{label}` for tone, `{fact_key, label, text}` for brand proof, …). */
export type CustomOption<B extends CustomBlock> = Extract<OptionProposal, { block: B }>["option"];
/** Returned by the caller: takes its change back when the user removes the 「你自訂」 item. */
export type CustomUndo = () => void;

const HINT = "覺得上面列的不對、不像你、或選項太少？直接用一句話描述，AI 幫你整理成選項";
const MAX_CHARS = 200;

interface Made {
  id: number;
  label: string;
  undo: CustomUndo | void;
}

export function CustomEscape<B extends CustomBlock>({ brandId, block, placeholder, onValue, onOption }: {
  brandId: string;
  block: B;
  placeholder: string;
  onValue?: (value: string) => CustomUndo | void;
  onOption?: (option: CustomOption<B>) => CustomUndo | void;
}) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [made, setMade] = useState<Made[]>([]);
  /** Bumped on cancel and on each request: a late answer to a cancelled request is dropped. */
  const ticket = useRef(0);
  const nextId = useRef(0);
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
      const proposal = await proposeCustom(brandId, block, sentence);
      if (mine !== ticket.current) return;
      let undo: CustomUndo | void;
      if (proposal.kind === "value") undo = handlers.current.onValue?.(proposal.value);
      else undo = handlers.current.onOption?.(proposal.option as CustomOption<B>);
      setMade((prev) => [...prev, { id: nextId.current++, label: madeLabel(proposal), undo }]);
      close();
    } catch (err) {
      if (mine !== ticket.current) return;
      setError(err instanceof Error ? err.message : "AI 整理不出來，換個說法再試一次");
      setBusy(false);
    }
  }

  function remove(item: Made) {
    item.undo?.();
    setMade((prev) => prev.filter((m) => m.id !== item.id));
  }

  return (
    <div data-slot="custom-escape" data-block={block}>
      {made.map((item) => (
        <div key={item.id} data-slot="custom-made" className="mt-2 flex items-center gap-2.5 rounded-[10px] border border-border bg-card px-3 py-2.5">
          <span className="inline-flex shrink-0 items-center rounded bg-zone-ok px-1.5 py-px text-[11px] font-semibold text-success-strong">你自訂</span>
          <div className="min-w-0 flex-1">
            <b className="block font-semibold [overflow-wrap:anywhere]">{item.label}</b>
            <div className="text-[11.5px] text-muted-foreground">AI 照你的描述整理；不對就再說一次</div>
          </div>
          <button type="button" aria-label={`拿掉「${item.label}」`} className="rounded p-1 text-lg leading-none text-muted-foreground hover:text-foreground" onClick={() => remove(item)}>
            ×
          </button>
        </div>
      ))}
      {open ? (
        <div className="mt-2.5 rounded-[10px] border border-dashed border-grade-thin bg-[#fcfbff] px-3 py-2.5">
          <div id={hintId} className="mb-1.5 text-[11.5px] text-muted-foreground">{HINT}</div>
          <textarea
            rows={2}
            aria-labelledby={hintId}
            className="w-full rounded-lg border border-input bg-card px-3 py-[9px] text-sm focus:border-primary focus:shadow-[0_0_0_3px_var(--color-accent)] focus:outline-none"
            placeholder={placeholder}
            maxLength={MAX_CHARS}
            value={text}
            disabled={busy}
            autoFocus
            onChange={(e) => setText(e.target.value)}
          />
          {error && <p role="alert" className="mt-1.5 text-xs text-danger">{error}</p>}
          <div className="mt-2 flex items-center gap-2">
            <Button type="button" variant="outline" size="sm" disabled={!text.trim() || busy} aria-busy={busy} onClick={() => void organise()}>
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
            className="rounded-full border border-dashed border-[#b9aef0] bg-card px-[13px] py-[5px] text-[13px] font-semibold text-accent-foreground hover:border-primary hover:bg-[#faf8ff]"
            onClick={() => setOpen(true)}
          >
            ✎ 自訂：用自己的話說
          </button>
        </div>
      )}
    </div>
  );
}

/** What the 「你自訂」 item names: the new value, or the option as the user will see it in the list. */
function madeLabel(p: CustomProposal): string {
  if (p.kind === "value") return p.value;
  switch (p.block) {
    case "tone":
      return p.option.label;
    case "brand_proof":
      return p.option.text || p.option.label;
    case "policy":
      return p.option.sentence || p.option.label;
    case "forbidden":
      return p.option.text;
  }
}
