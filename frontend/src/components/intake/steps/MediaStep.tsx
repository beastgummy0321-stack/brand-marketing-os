import { useWorkspace } from "@/components/layout/WorkspaceContext";
import { brandDraftKey, clearStepDraft, readStepDraft, useStepDraft } from "../shared/stepDraft";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { useParams } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { fetchOnboardingMedia, saveOnboardingMedia, type MediaCapability } from "@/lib/intakeOnboardingApi";
import { cn } from "@/lib/utils";
import { BarNext, OnboardingBar, OnboardingStepHead, type BarBack, type StepNav } from "../OnboardingStepHead";

/** Prototype `R.b5` cards: value, title, note. */
const OPTIONS: [MediaCapability, string, string][] = [
  ["photo", "只有照片", "排單圖、輪播；不排影片"],
  ["photo_video", "照片和影片都能交", "影片自己拍好上傳"],
];

/** A brand never asked shows 「只有照片」 picked, as the prototype does; it is written only on 下一步. */
const DEFAULT_MEDIA: MediaCapability = "photo";

type LoadState = { status: "loading" } | { status: "error"; message: string } | { status: "ready" };

/** Brand onboarding #/b5 素材 (prototype `R.b5` of `.harness/scratch/prototype/f41-onboarding/index.html`): which
 * media the owner can deliver — the planner never schedules a video slot for a photo-only brand. Nothing is saved
 * until 下一步 (`PUT …/onboarding/media`); a failed save keeps the user on the step. The brand comes from the
 * route (`/brands/:brandId/intake`), the only place this step renders. */
export function MediaStep({ nav, back, onNext }: { nav: StepNav; back?: BarBack; onNext: () => void }) {
  const { brandId = "" } = useParams<{ brandId: string }>();
  const { scope } = useWorkspace();
  const draftKey = brandDraftKey(scope, brandId, "media");
  const [baseline, setBaseline] = useState<MediaCapability>(DEFAULT_MEDIA);
  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const [media, setMedia] = useState<MediaCapability>(DEFAULT_MEDIA);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function reload() {
    setLoad({ status: "loading" });
    fetchOnboardingMedia(brandId)
      .then((data) => {
        const saved = data.media ?? DEFAULT_MEDIA;
        setBaseline(saved);
        setMedia(readStepDraft(draftKey, (v): v is MediaCapability => v === "photo" || v === "photo_video") ?? saved);
        setLoad({ status: "ready" });
      })
      .catch((err: unknown) => setLoad({ status: "error", message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。" }));
  }

  useEffect(reload, [brandId]);

  useStepDraft(draftKey, load.status === "ready", media, baseline);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await saveOnboardingMedia(brandId, media);
      clearStepDraft(draftKey);
      setBaseline(media);
      onNext();
    } catch (err) {
      setError(err instanceof Error ? err.message : "處理失敗，請稍後再試。");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <OnboardingStepHead {...nav} title="你交得出哪些素材" purpose="系統目前做不出照片和影片，要靠你拍；規劃只會排你交得出來的" />
      {load.status === "error" ? (
        <div className="flex flex-col items-start gap-2 rounded-xl border border-border bg-card px-[22px] py-5">
          <p role="alert" className="text-sm text-danger">{load.message}</p>
          <Button type="button" variant="link" className="h-auto p-0 text-[13px]" onClick={reload}>重新載入</Button>
        </div>
      ) : (
        <section className="rounded-xl border border-border bg-card px-[22px] py-5">
          <MediaPick value={media} busy={load.status !== "ready"} onChange={setMedia} />
          <p className="mt-3 text-[11.5px] text-muted-foreground">之後拍得出影片了，回到「品牌資料」改就好。</p>
        </section>
      )}
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      <OnboardingBar back={back}>
        <BarNext label={saving ? "處理中…" : "下一步"} busy={load.status === "loading" || saving} disabledReason={load.status === "error" ? "先重新載入素材資料" : null} onClick={() => void save()} />
      </OnboardingBar>
    </div>
  );
}

/** Prototype `.pick` + `.pk`: two single-choice cards, radio keyboard pattern (the picked card is the tab stop;
 * arrows and Home/End move to and pick a card). The kit's `PickCard` is not on `components/ads`' public entry, and
 * this prototype's card is the compact `.pk` (title + one note line, no icon tile). */
function MediaPick({ value, busy, onChange }: { value: MediaCapability; busy: boolean; onChange: (v: MediaCapability) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const keys = ["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp", "Home", "End"];
    if (busy || !keys.includes(e.key) || !ref.current) return;
    e.preventDefault();
    const radios = Array.from(ref.current.querySelectorAll<HTMLButtonElement>("[role=radio]"));
    const at = radios.indexOf(document.activeElement as HTMLButtonElement);
    const next = e.key === "Home" ? 0
      : e.key === "End" ? radios.length - 1
      : e.key === "ArrowRight" || e.key === "ArrowDown" ? (at + 1) % radios.length
      : (at - 1 + radios.length) % radios.length;
    radios[next].focus();
    onChange(OPTIONS[next][0]);
  };
  return (
    <div ref={ref} data-slot="pick-group" role="radiogroup" aria-label="你交得出哪些素材" onKeyDown={onKeyDown} className="flex flex-wrap gap-3">
      {OPTIONS.map(([key, title, note]) => {
        const checked = value === key;
        return (
          <Button
            key={key}
            type="button"
            role="radio"
            aria-checked={checked}
            data-slot="pick-card"
            data-value={key}
            data-variant={checked ? "picked" : "open"}
            busy={busy}
            tabIndex={checked ? 0 : -1}
            onClick={() => onChange(key)}
            className={cn(
              "flex min-w-[180px] flex-col items-start rounded-[10px] border px-3.5 py-3 text-left transition-colors disabled:cursor-default",
              checked ? "border-primary bg-accent/50 shadow-[0_0_0_1px_var(--color-primary)]" : "border-border bg-card hover:border-primary",
            )}
          >
            <b className="text-sm font-semibold">{title}</b>
            <span className="text-xs text-muted-foreground">{note}</span>
          </Button>
        );
      })}
    </div>
  );
}
