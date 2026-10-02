import { useEffect, useRef, useState, type ReactNode } from "react";
import { Input } from "@/components/layout/ui/input";
import type { CustomerGroupInput, PainKey, ProductWho } from "@/lib/intakeProductApi";
import { fetchProductWho, proposeProductCustom, saveProductWho } from "@/lib/intakeProductApi";
import { useFormSubmit } from "@/lib/useFormSubmit";
import { cn } from "@/lib/utils";
import { BarNext, OnboardingBar, OnboardingStepHead, type BarBack, type StepNav } from "../OnboardingStepHead";
import { AiTag } from "../shared/AiTag";
import { clearStepDraft, CustomEscape, CustomMark, productDraftKey, readStepDraft, useStepDraft } from "../shared/CustomEscape";

/** Prototype `R.p2` head of `.harness/scratch/prototype/f41-onboarding/index.html`. */
const TITLE = "誰會買、買之前煩什麼";
const PURPOSE = "規劃用這裡決定每則廣告對誰說、說什麼";
/** At most three groups; each picks 1–2 pains (prototype `chips(key, PAINS, 2)`: a third drops the oldest). */
const MAX_GROUPS = 3;
const MAX_PAINS = 2;
const IN = "h-auto w-full rounded-lg bg-card px-3 py-[9px] text-sm shadow-none";

type Content = { who: string; pain_keys: PainKey[]; quote: string; when_used: string };
/** Where a group came from: the saved row, the product-page read's proposal, or 「自訂」. */
type Origin = "saved" | "ai" | "custom";

interface Draft extends Content {
  key: number;
  id: string | null;
  origin: Origin;
  note: string;
  /** The content as loaded / proposed: the origin's tag shows while the group still holds it. */
  base: Content;
  /** The quote a 「自訂」 pain filled in: marked 你自訂 while the field still holds it. */
  customQuote: string | null;
}

const sameContent = (a: Content, b: Content) =>
  a.who === b.who && a.quote === b.quote && a.when_used === b.when_used &&
  a.pain_keys.length === b.pain_keys.length && a.pain_keys.every((k, i) => k === b.pain_keys[i]);

/** The first group 下一步 cannot save yet, as the bar's reason. */
function blockedReason(groups: Draft[]): string | null {
  for (const [i, g] of groups.entries()) {
    if (!g.who.trim()) return `第 ${i + 1} 群還沒寫是誰`;
    if (g.pain_keys.length === 0) return `第 ${i + 1} 群還沒挑煩惱`;
  }
  return null;
}

/** This step's draft (F47-I03, `useStepDraft`): every group but its render key. */
type KeptGroup = Omit<Draft, "key">;

const kept = (groups: Draft[]): KeptGroup[] => groups.map(({ key: _key, ...rest }) => rest);

const isContent = (v: unknown): v is Content => {
  const c = v as Record<string, unknown> | null;
  return !!c && typeof c.who === "string" && typeof c.quote === "string" && typeof c.when_used === "string"
    && Array.isArray(c.pain_keys) && c.pain_keys.every((k) => typeof k === "string");
};

function isKeptGroups(v: unknown): v is KeptGroup[] {
  return Array.isArray(v) && v.length <= MAX_GROUPS && v.every((g: Record<string, unknown>) =>
    isContent(g.base) && (g.id === null || typeof g.id === "string")
    && (g.origin === "saved" || g.origin === "ai" || g.origin === "custom") && typeof g.note === "string"
    && (g.customQuote === null || typeof g.customQuote === "string") && isContent(g));
}

function toInput(g: Draft): CustomerGroupInput {
  const unchanged = sameContent(g, g.base);
  return {
    id: g.id,
    who: g.who.trim(),
    pain_keys: g.pain_keys,
    quote: g.quote.trim(),
    when_used: g.when_used.trim(),
    source: unchanged ? g.origin : "user",
  };
}

/** Product onboarding `#/p2` 誰會買、買之前煩什麼 (prototype `R.p2`): up to three customer groups from
 * `GET …/onboarding/who` (saved rows, or the product-page read's proposals with their tag), each with 是誰, 1–2 of the
 * six pains (`pain_options`) + 顧客會怎麼說 + 「自訂」 (product block `pain`: checks the mapped pain and fills the quote,
 * marked 你自訂), 什麼時候用 and a remove ×. Under the groups 「自訂」 (block `group`) appends a group marked 你自訂; it
 * hides at three. 下一步 saves the full list through `PUT …/onboarding/who` and moves on only after the server
 * confirmed; a group without 是誰 or without a pain keeps 下一步 off with the reason in the bar. */
export function WhoStep({ brandId, productId, nav, back, onNext }: {
  brandId: string;
  productId: string;
  nav: StepNav;
  back: BarBack;
  onNext: () => void;
}) {
  const draftKey = productDraftKey(brandId, productId, "who");
  const [loaded, setLoaded] = useState<ProductWho | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [groups, setGroups] = useState<Draft[]>([]);
  /** The groups as loaded (before any edit): the draft is kept only while `groups` differ from it. */
  const [loadedGroups, setLoadedGroups] = useState<KeptGroup[]>([]);
  const nextKey = useRef(0);

  const draft = (content: Content, extra: { id: string | null; origin: Origin; note: string }): Draft => ({
    ...content,
    ...extra,
    key: nextKey.current++,
    base: content,
    customQuote: null,
  });

  useEffect(() => {
    let cancelled = false;
    fetchProductWho(brandId, productId)
      .then((who) => {
        if (cancelled) return;
        const fromServer = who.groups.slice(0, MAX_GROUPS).map((g) =>
          draft(
            { who: g.who, pain_keys: g.pain_keys.slice(0, MAX_PAINS), quote: g.quote, when_used: g.when_used },
            { id: g.id, origin: g.source === "ai" ? "ai" : "saved", note: g.note },
          ),
        );
        // F47-I03 (drill-10 乙 #1, faults F7): unsaved groups (an AI-organised 自訂 group included) come
        // back when the step mounts again -- back, step bar or reload -- until 下一步 saved them.
        const restored = readStepDraft(draftKey, isKeptGroups);
        setLoadedGroups(kept(fromServer));
        setLoaded(who);
        setGroups(restored ? restored.map((g) => ({ ...g, key: nextKey.current++ })) : fromServer);
      })
      .catch((err: unknown) => {
        if (!cancelled) setLoadError(err instanceof Error ? err.message : "讀取失敗，請稍後再試。");
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brandId, productId]);

  useStepDraft(draftKey, loaded !== null, kept(groups), loadedGroups);

  const { saving, error, submit, formProps } = useFormSubmit(async () => {
    await saveProductWho(brandId, productId, groups.map(toInput));
    clearStepDraft(draftKey);
    onNext();
  });

  const head = <OnboardingStepHead {...nav} title={TITLE} purpose={PURPOSE} />;

  if (loadError) {
    return (
      <div className="flex flex-col gap-4">
        {head}
        <p role="alert" className="text-sm text-danger">{loadError}</p>
        <OnboardingBar back={back} />
      </div>
    );
  }

  const update = (key: number, change: (g: Draft) => Partial<Draft>) =>
    setGroups((prev) => prev.map((g) => (g.key === key ? { ...g, ...change(g) } : g)));
  const togglePain = (key: number, pain: PainKey) =>
    update(key, (g) => ({
      pain_keys: g.pain_keys.includes(pain) ? g.pain_keys.filter((k) => k !== pain) : [...g.pain_keys, pain].slice(-MAX_PAINS),
    }));

  const reason = loaded ? blockedReason(groups) : null;
  const propose = (block: "group" | "pain") => (text: string) => proposeProductCustom(brandId, productId, block, text);

  return (
    <form
      className="flex flex-col gap-4"
      {...formProps}
      onSubmit={(e) => {
        e.preventDefault();
        if (loaded && !reason && !saving) void submit();
      }}
    >
      {head}
      {loaded && (
        <section className="rounded-xl border border-border bg-card px-[22px] py-5">
          {groups.map((g, i) => (
            <GroupBox
              key={g.key}
              n={i + 1}
              group={g}
              painOptions={loaded.pain_options}
              brandId={brandId}
              proposePain={propose("pain")}
              onChange={(change) => update(g.key, () => change)}
              onTogglePain={(pain) => togglePain(g.key, pain)}
              onCustomPain={({ pain_key, quote }) =>
                update(g.key, (cur) => ({
                  pain_keys: cur.pain_keys.includes(pain_key) ? cur.pain_keys : [...cur.pain_keys, pain_key].slice(-MAX_PAINS),
                  ...(quote.trim() ? { quote, customQuote: quote } : {}),
                }))
              }
              onRemove={() => setGroups((prev) => prev.filter((x) => x.key !== g.key))}
            />
          ))}
          {groups.length < MAX_GROUPS && (
            <CustomEscape
              brandId={brandId}
              block="group"
              placeholder="例如：買給爸媽的子女，怕長輩吞不下藥丸"
              propose={propose("group")}
              onOption={(option) =>
                setGroups((prev) =>
                  prev.length >= MAX_GROUPS
                    ? prev
                    : [
                        ...prev,
                        draft(
                          { who: option.who, pain_keys: option.pain_keys.slice(0, MAX_PAINS), quote: option.quote, when_used: option.when_used },
                          { id: null, origin: "custom", note: "" },
                        ),
                      ],
                )
              }
            />
          )}
          <p className="mt-1.5 text-[11.5px] text-muted-foreground">最多 3 群；AI 會把你的描述整理成一群、並對上煩惱類型</p>
        </section>
      )}

      {error && <p role="alert" className="text-sm text-danger">{error}</p>}

      <OnboardingBar back={back} hint={reason ?? undefined}>
        <BarNext type="submit" label="下一步" disabled={!loaded || !!reason || saving} />
      </OnboardingBar>
    </form>
  );
}

/** Prototype `group(n, …)` (`.grp`): 第 N 群 + its tag and ×, then 是誰 / 買之前最煩什麼 / 什麼時候用. */
function GroupBox({ n, group, painOptions, brandId, proposePain, onChange, onTogglePain, onCustomPain, onRemove }: {
  n: number;
  group: Draft;
  painOptions: ProductWho["pain_options"];
  brandId: string;
  proposePain: (text: string) => ReturnType<typeof proposeProductCustom>;
  onChange: (change: Partial<Content>) => void;
  onTogglePain: (pain: PainKey) => void;
  onCustomPain: (option: { pain_key: PainKey; quote: string }) => void;
  onRemove: () => void;
}) {
  const id = `p2-g${group.key}`;
  const unchanged = sameContent(group, group.base);
  let tag: ReactNode = null;
  if (unchanged && group.origin === "ai") tag = <AiTag source="ai" note={group.note} />;
  else if (unchanged && group.origin === "custom") tag = <CustomMark />;

  return (
    <div role="group" aria-label={`第 ${n} 群`} className={cn("rounded-xl border border-border bg-background/30 px-4 py-3.5", n > 1 && "mt-2.5")}>
      <div className="flex items-center justify-between gap-2">
        <b className="text-sm font-semibold">第 {n} 群</b>
        <div className="flex items-center gap-1">
          {tag}
          <button type="button" aria-label={`拿掉第 ${n} 群`} className="rounded p-1 text-lg leading-none text-muted-foreground hover:text-foreground" onClick={onRemove}>
            ×
          </button>
        </div>
      </div>
      <GroupRow first label={<label htmlFor={`${id}-who`}>是誰</label>}>
        <Input id={`${id}-who`} className={IN} value={group.who} maxLength={100} onChange={(e) => onChange({ who: e.target.value })} />
      </GroupRow>
      <GroupRow label="買之前最煩什麼" note="挑 1～2 個">
        <div role="group" aria-label="買之前最煩什麼" className="flex flex-wrap gap-2">
          {painOptions.map(({ key, label }) => {
            const on = group.pain_keys.includes(key);
            return (
              <button
                key={key}
                type="button"
                aria-pressed={on}
                onClick={() => onTogglePain(key)}
                className={cn(
                  "rounded-full border px-[13px] py-[5px] text-[13px] font-medium hover:border-primary",
                  on ? "border-primary bg-accent/40 text-accent-foreground shadow-[0_0_0_1px_var(--color-primary)]" : "border-border bg-card",
                )}
              >
                {label}
              </button>
            );
          })}
        </div>
        <Input
          aria-label="顧客會怎麼說"
          placeholder="顧客會怎麼說"
          className={cn(IN, "mt-2")}
          value={group.quote}
          maxLength={200}
          onChange={(e) => onChange({ quote: e.target.value })}
        />
        {group.customQuote !== null && group.quote === group.customQuote && <div className="mt-1"><CustomMark /></div>}
        <CustomEscape
          brandId={brandId}
          block="pain"
          placeholder="例如：怕吃了跟藥物衝突"
          propose={proposePain}
          onOption={({ pain_key, quote }) => onCustomPain({ pain_key, quote })}
        />
      </GroupRow>
      <GroupRow label={<label htmlFor={`${id}-when`}>什麼時候用</label>}>
        <Input id={`${id}-when`} className={IN} value={group.when_used} maxLength={100} onChange={(e) => onChange({ when_used: e.target.value })} />
      </GroupRow>
    </div>
  );
}

/** Prototype `.q` inside a group (130px label column; every row under the group title has a rule above it). */
function GroupRow({ label, note, first, children }: { label: ReactNode; note?: string; first?: boolean; children: ReactNode }) {
  return (
    <div className={cn("grid grid-cols-[130px_minmax(0,1fr)] items-start gap-x-5 gap-y-2.5 border-t border-border py-3.5 max-[760px]:grid-cols-1", first && "pt-2.5")}>
      <div>
        <b className="block text-sm font-semibold">{label}</b>
        {note && <span className="mt-0.5 block text-xs text-muted-foreground">{note}</span>}
      </div>
      <div className="min-w-0">{children}</div>
    </div>
  );
}
