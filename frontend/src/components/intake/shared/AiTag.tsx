import type { OnboardingSource } from "@/lib/intakeOnboardingApi";

/** The small tag under an AI-prefilled onboarding field, prototype `AI(t)` / `NOAI` of
 * `.harness/scratch/prototype/f41-onboarding/index.html` (`.ai`, `.ai.no`): `ai` = the website/photo
 * scan proposed it (「✦ 〈note〉」, 「✦ AI 從網站讀到」 when the scan gave no note), `none` = the scan
 * found nothing (「網站上沒找到」), `saved` = the user already confirmed it (no tag). */
export function AiTag({ source, note }: { source: OnboardingSource; note?: string }) {
  if (source === "saved") return null;
  if (source === "none") {
    return (
      <span data-slot="ai-tag" data-source="none" className="inline-flex items-center gap-1 rounded px-1.5 py-px text-[11px] font-semibold whitespace-nowrap bg-muted text-muted-foreground">
        網站上沒找到
      </span>
    );
  }
  return (
    <span data-slot="ai-tag" data-source="ai" className="inline-flex items-center gap-1 rounded px-1.5 py-px text-[11px] font-semibold whitespace-nowrap bg-accent text-accent-foreground">
      ✦ {note?.trim() || "AI 從網站讀到"}
    </span>
  );
}
