import { useEffect, useState, type ReactNode } from "react";
import { useParams } from "react-router-dom";
import { useWorkspace } from "@/components/layout/WorkspaceContext";
import type { OnboardingIdentity } from "@/lib/intakeOnboardingApi";
import { fetchOnboardingIdentity, saveOnboardingIdentity } from "@/lib/intakeOnboardingApi";
import { useAuthedImage } from "@/lib/useAuthedImage";
import { useFormSubmit } from "@/lib/useFormSubmit";
import { cn } from "@/lib/utils";
import { BarNext, OnboardingBar, OnboardingStepHead, type BarBack, type StepNav } from "../OnboardingStepHead";
import { AiTag } from "../shared/AiTag";
import { clearStepDraft, CustomEscape, CustomMark, readStepDraft, useStepDraft } from "../shared/CustomEscape";

/** Prototype `chips(…, 2)`: at most two tones; picking a third drops the oldest. */
const TONE_MAX = 2;

/** Brand onboarding `#/b3` 品牌是誰 (prototype `R.b3` of `.harness/scratch/prototype/f41-onboarding/index.html`):
 * positioning, tone (1–2) and visual style, pre-filled from `GET …/onboarding/identity` with the scan's tag
 * until the user changes the field; each block ends with 「自訂」, whose result shows where it lives (the field's
 * tag reads 「你自訂」; a new tone joins the chips marked 「你自訂」 with its own ×). 下一步 saves the three through
 * `PUT …/onboarding/identity` and moves on only after the server confirmed; an error keeps the user here. */
export function IdentityStep({ nav, back, onNext }: { nav: StepNav; back?: BarBack; onNext: () => void }) {
  const { brandId = "" } = useParams<{ brandId: string }>();
  const { scope } = useWorkspace();
  const draftKey = `intake-draft:${scope ?? ""}:${brandId}:identity`;
  const [loaded, setLoaded] = useState<OnboardingIdentity | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [positioning, setPositioning] = useState("");
  const [tones, setTones] = useState<string[]>([]);
  const [toneOptions, setToneOptions] = useState<string[]>([]);
  const [visual, setVisual] = useState("");
  /** 自訂 results: the value a field was filled with, and the tones 自訂 added to the chips. */
  const [customPositioning, setCustomPositioning] = useState<string | null>(null);
  const [customVisual, setCustomVisual] = useState<string | null>(null);
  const [customTones, setCustomTones] = useState<string[]>([]);

  useEffect(() => {
    let cancelled = false;
    fetchOnboardingIdentity(brandId)
      .then((identity) => {
        if (cancelled) return;
        // F47-I03: unsaved edits of this step (left with 「← 上一步」, a step-bar jump or a reload) come
        // back over the loaded values; the draft is dropped once 下一步 saved.
        const draft = readStepDraft(draftKey, isIdentityDraft);
        const text = draft ?? baseline(identity);
        setLoaded(identity);
        setPositioning(text.positioning);
        setTones(text.tones);
        setToneOptions(text.toneOptions);
        setVisual(text.visual);
        setCustomPositioning(text.customPositioning);
        setCustomVisual(text.customVisual);
        setCustomTones(text.customTones);
      })
      .catch((err: unknown) => {
        if (!cancelled) setLoadError(err instanceof Error ? err.message : "讀取失敗，請稍後再試。");
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brandId]);

  const current: IdentityDraft = { positioning, tones, toneOptions, visual, customPositioning, customVisual, customTones };
  useStepDraft(draftKey, loaded !== null, current, loaded ? baseline(loaded) : null);

  const { saving, error, submit, formProps } = useFormSubmit(async () => {
    await saveOnboardingIdentity(brandId, { positioning: positioning.trim(), tone: tones, visual: visual.trim() });
    clearStepDraft(draftKey);
    onNext();
  });

  const head = <OnboardingStepHead {...nav} title="品牌是誰" purpose="廣告的口氣和畫面跟著這裡走" />;

  if (loadError) {
    return (
      <div className="flex flex-col gap-4">
        {head}
        <p role="alert" className="text-sm text-danger">{loadError}</p>
        <OnboardingBar back={back} />
      </div>
    );
  }

  function pickTone(tone: string) {
    setTones((prev) => {
      if (prev.includes(tone)) return prev.filter((t) => t !== tone);
      return [...prev, tone].slice(-TONE_MAX);
    });
  }

  function removeCustomTone(tone: string) {
    setToneOptions((prev) => prev.filter((t) => t !== tone));
    setTones((prev) => prev.filter((t) => t !== tone));
    setCustomTones((prev) => prev.filter((t) => t !== tone));
  }

  return (
    <form
      className="flex flex-col gap-4"
      {...formProps}
      onSubmit={(e) => {
        e.preventDefault();
        if (loaded && !saving) void submit();
      }}
    >
      {head}
      {loaded && (
        <section className="rounded-xl border border-border bg-card px-[22px] py-5">
          <Row label={<label htmlFor="b3-positioning">一句話說你的品牌</label>} note="寫給顧客看的那種">
            <textarea
              id="b3-positioning"
              rows={2}
              className="w-full rounded-lg border border-input bg-card px-3 py-[9px] text-sm focus:border-primary focus:shadow-[0_0_0_3px_var(--color-accent)] focus:outline-none focus-visible:outline-none"
              value={positioning}
              onChange={(e) => setPositioning(e.target.value)}
            />
            {positioning === customPositioning
              ? <div className="mt-1"><CustomMark /></div>
              : positioning === loaded.positioning.value && <Tag source={loaded.positioning.source} note={loaded.positioning.note} />}
            <CustomEscape
              brandId={brandId}
              block="positioning"
              placeholder="例如：我們不是保健品，是給懶人的營養零食"
              onValue={(value) => {
                setPositioning(value);
                setCustomPositioning(value);
              }}
            />
          </Row>
          <Row label="說話的口氣" note="挑 1～2 個">
            <div role="group" aria-label="說話的口氣" className="flex flex-wrap gap-2">
              {toneOptions.map((tone) => {
                const on = tones.includes(tone);
                const chip = (
                  <button
                    key={tone}
                    type="button"
                    aria-pressed={on}
                    onClick={() => pickTone(tone)}
                    className={cn(
                      "rounded-full border px-[13px] py-[5px] text-[13px] font-medium hover:border-primary",
                      on ? "border-primary bg-accent/40 text-accent-foreground shadow-[0_0_0_1px_var(--color-primary)]" : "border-border bg-card",
                    )}
                  >
                    {tone}
                  </button>
                );
                if (!customTones.includes(tone)) return chip;
                return (
                  <span key={tone} className="inline-flex items-center gap-1">
                    {chip}
                    <CustomMark />
                    <button type="button" aria-label={`拿掉「${tone}」`} className="rounded p-1 text-lg leading-none text-muted-foreground hover:text-foreground" onClick={() => removeCustomTone(tone)}>
                      ×
                    </button>
                  </span>
                );
              })}
            </div>
            {sameTones(tones, loaded.tone.values) && <Tag source={loaded.tone.source} note={loaded.tone.note} gap="mt-1.5" />}
            <CustomEscape
              brandId={brandId}
              block="tone"
              placeholder="例如：像健身房的教練朋友，講話直、偶爾吐槽"
              onOption={({ label }) => {
                const isNew = !toneOptions.includes(label);
                if (isNew) {
                  setToneOptions((prev) => [...prev, label]);
                  setCustomTones((prev) => [...prev, label]);
                }
                setTones((prev) => (prev.includes(label) ? prev : [...prev, label].slice(-TONE_MAX)));
              }}
            />
          </Row>
          <Row label="畫面風格" note="從你的產品照看出來的">
            <div className="flex flex-wrap items-center gap-3">
              {loaded.visual.photo_urls.map((url) => (
                <Thumb key={url} url={url} />
              ))}
              {visual && <span className="text-[12.5px]">{visual}</span>}
              {visual === customVisual
                ? <CustomMark />
                : visual === loaded.visual.value && <AiTag source={loaded.visual.source} note={loaded.visual.note} />}
            </div>
            <div className="mt-3.5">
              <CustomEscape
                brandId={brandId}
                block="visual"
                placeholder="例如：黑底、霓虹感、健身房器材，不要粉嫩"
                onValue={(value) => {
                  setVisual(value);
                  setCustomVisual(value);
                }}
              />
            </div>
          </Row>
        </section>
      )}

      {error && <p role="alert" className="text-sm text-danger">{error}</p>}

      <OnboardingBar back={back}>
        <BarNext type="submit" label="下一步" disabled={!loaded || saving} />
      </OnboardingBar>
    </form>
  );
}

/** This step's unsaved edits, kept per user scope and brand in `sessionStorage` (F47-I03, drill-10 甲 建檔 #5,
 * faults F3): restored when the step mounts again (back, step bar, reload), cleared once 下一步 saved or when
 * the fields hold the loaded values again. */
interface IdentityDraft {
  positioning: string;
  tones: string[];
  toneOptions: string[];
  visual: string;
  customPositioning: string | null;
  customVisual: string | null;
  customTones: string[];
}

function baseline(identity: OnboardingIdentity): IdentityDraft {
  return {
    positioning: identity.positioning.value,
    tones: identity.tone.values.slice(0, TONE_MAX),
    toneOptions: withTones(identity.tone.options, identity.tone.values),
    visual: identity.visual.value,
    customPositioning: null,
    customVisual: null,
    customTones: [],
  };
}

const isStrings = (v: unknown): v is string[] => Array.isArray(v) && v.every((x) => typeof x === "string");
const isTextOrNull = (v: unknown) => v === null || typeof v === "string";

function isIdentityDraft(value: unknown): value is IdentityDraft {
  const v = value as Record<string, unknown>;
  return typeof v === "object" && typeof v.positioning === "string" && typeof v.visual === "string" && isStrings(v.tones)
    && isStrings(v.toneOptions) && isStrings(v.customTones) && isTextOrNull(v.customPositioning) && isTextOrNull(v.customVisual);
}

/** The step's option list plus any pre-filled tone the list does not carry (an AI tone outside the vocabulary). */
function withTones(options: string[], values: string[]): string[] {
  return [...options, ...values.filter((v) => !options.includes(v))];
}

function sameTones(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((t) => b.includes(t));
}

function Tag({ source, note, gap = "mt-1" }: { source: OnboardingIdentity["positioning"]["source"]; note: string; gap?: string }) {
  if (source === "saved") return null;
  return (
    <div className={gap}>
      <AiTag source={source} note={note} />
    </div>
  );
}

/** Prototype `.q`: label column (bold + one small note) and the field. */
function Row({ label, note, children }: { label: ReactNode; note?: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[170px_minmax(0,1fr)] items-start gap-x-5 gap-y-2.5 border-t border-border py-3.5 first:border-t-0 first:pt-0 last:pb-0">
      <div>
        <b className="block text-sm font-semibold">{label}</b>
        {note && <span className="mt-0.5 block text-xs text-muted-foreground">{note}</span>}
      </div>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

/** Prototype `th(…, 56)`: a brand photo thumbnail. */
function Thumb({ url }: { url: string }) {
  const { src } = useAuthedImage(url);
  return src
    ? <img src={src} alt="" className="size-14 rounded-lg object-cover" />
    : <span className="size-14 rounded-lg bg-muted" aria-hidden="true" />;
}
