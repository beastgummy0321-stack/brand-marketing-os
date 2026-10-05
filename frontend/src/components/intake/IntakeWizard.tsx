import { ApiResponseError } from "@/lib/http";
import { useEffect, useState, type ReactNode } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useWorkspace } from "@/components/layout/WorkspaceContext";
import { EmptyState } from "@/components/layout/EmptyState";
import type { IntakeDraft } from "@/lib/intakeApi";
import { fetchIntakeDraft } from "@/lib/intakeApi";
import type { OnboardingStatus } from "@/lib/intakeOnboardingApi";
import { completeOnboarding, fetchOnboardingStatus } from "@/lib/intakeOnboardingApi";
import { BRAND_STEPS, brandCrumb, type BarBack, type StepNav } from "./OnboardingStepHead";
import { DoneStep } from "./steps/DoneStep";
import { EvidenceStep } from "./steps/EvidenceStep";
import { IdentityStep } from "./steps/IdentityStep";
import { MediaStep } from "./steps/MediaStep";
import { ScanStep } from "./steps/ScanStep";
import { StartStep } from "./steps/StartStep";
import { ToolsStep } from "./steps/ToolsStep";

const LAST_STEP = BRAND_STEPS.length;
const SCAN_STEP = 2;

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "notfound" }
  | { status: "ready"; onboarding: OnboardingStatus; draft: IntakeDraft | null };

/** Brand onboarding, seven steps (prototype `#/b1`–`#/b7` of
 * `.harness/scratch/prototype/f41-onboarding/index.html`). `brandId === null` is a new brand
 * (`/intake/new`): step 1 creates it. Otherwise `GET …/onboarding` says where the brand is:
 * an open draft walks forward from its step; a completed brand (re-entry) opens step 7, or step N
 * with `?step=N`. Step 2 (AI 讀網站) is skipped when the brand gave no website and no photo. */
export function IntakeWizard({ brandId }: { brandId: string | null }) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { refreshBrands, brands } = useWorkspace();
  const [state, setState] = useState<LoadState>(brandId ? { status: "loading" } : { status: "notfound" });
  const [furthest, setFurthest] = useState(1);
  const requested = parseStepParam(searchParams.get("step"));
  const ready = state.status === "ready" ? state : null;
  const scanSkipped = ready ? ready.onboarding.skipped_scan || ready.draft === null : false;
  const scanCanContinue = ready && (scanSkipped || ready.draft?.scan_done || ["done", "failed"].includes(ready.onboarding.prefill_status));
  const reachable = ready ? (ready.onboarding.completed ? LAST_STEP : Math.max(furthest, ready.onboarding.step, scanCanContinue ? 3 : 1)) : 1;
  const fallback = ready ? (ready.onboarding.completed ? LAST_STEP : ready.onboarding.step) : 1;
  const chosen = requested !== null && requested <= reachable ? requested : fallback;
  const current = chosen === SCAN_STEP && scanSkipped ? SCAN_STEP + 1 : chosen;
  useEffect(() => {
    if (brandId && ready && searchParams.get("step") !== String(current)) {
      navigate(`/brands/${encodeURIComponent(brandId)}/intake?step=${current}`, { replace: true });
    }
  }, [brandId, ready, current, searchParams, navigate]);
  const [flowError, setFlowError] = useState<string | null>(null);

  async function refresh(): Promise<OnboardingStatus | null> {
    if (!brandId) return null;
    try {
      const [onboarding, draft] = await Promise.all([
        fetchOnboardingStatus(brandId),
        // Only read to skip step 2 for a brand without a draft; a brand without one still has onboarding.
        fetchIntakeDraft(brandId).catch(() => null),
      ]);
      setState({ status: "ready", onboarding, draft });
      return onboarding;
    } catch (err) {
      if (err instanceof ApiResponseError && err.status === 404) setState({ status: "notfound" });
      else setState({ status: "error", message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。" });
      return null;
    }
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brandId]);

  if (!brandId) {
    return (
      <Page>
        <StartStep
          brandId={null}
          nav={{ crumb: brandCrumb(""), steps: BRAND_STEPS, current: 1 }}
          onSaved={async ({ brand_id }) => {
            refreshBrands();
            const onboarding = await fetchOnboardingStatus(brand_id);
            navigate(`/brands/${encodeURIComponent(brand_id)}/intake?step=${onboarding.step}`, { replace: true });
          }}
        />
      </Page>
    );
  }

  if (state.status === "loading") {
    return <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">讀取中…</div>;
  }
  if (state.status === "notfound") {
    return <EmptyState title="找不到這個品牌" description="這個品牌可能已經刪除，或你沒有權限查看。" />;
  }
  if (state.status === "error") {
    return <EmptyState title="讀取失敗" description={state.message} onAction={() => void refresh()} actionLabel="重新載入" />;
  }

  const { onboarding } = state;
  const brandName = (brands ?? []).find((b) => b.brand_id === brandId)?.brand_name ?? "";
  const intakePath = `/brands/${encodeURIComponent(brandId)}/intake`;

  function goTo(step: number) {
    setFlowError(null);
    navigate(`${intakePath}?step=${step}`);
  }
  const nextOf = (step: number, skipped: boolean) => (step + 1 === SCAN_STEP && skipped ? SCAN_STEP + 1 : step + 1);
  const prevOf = (step: number) => (step - 1 === SCAN_STEP && scanSkipped ? SCAN_STEP - 1 : step - 1);
  const back: BarBack | undefined = current > 1 ? { label: BRAND_STEPS[prevOf(current) - 1], onClick: () => goTo(prevOf(current)) } : undefined;
  const next = () => {
    const step = nextOf(current, scanSkipped);
    setFurthest((previous) => Math.max(previous, step));
    goTo(step);
  };

  const nav: StepNav = {
    crumb: brandCrumb(brandName),
    steps: BRAND_STEPS,
    current,
    canSelect: (step) => step <= reachable && !(step === SCAN_STEP && scanSkipped),
    onSelect: goTo,
  };

  async function finishTools() {
    if (onboarding.completed) return goTo(LAST_STEP);
    try {
      await completeOnboarding(brandId as string);
      await refresh();
      navigate(`${intakePath}?step=${LAST_STEP}`);
    } catch (err) {
      setFlowError(err instanceof Error ? err.message : "處理失敗，請稍後再試。");
    }
  }

  let body;
  switch (current) {
    case 1:
      body = (
        <StartStep
          brandId={brandId}
          nav={nav}
          onSaved={async () => {
            const fresh = await refresh();
            if (fresh) goTo(nextOf(1, fresh.skipped_scan));
          }}
        />
      );
      break;
    case 2:
      body = <ScanStep brandId={brandId} nav={nav} back={back} onNext={next} />;
      break;
    case 3:
      body = <IdentityStep nav={nav} back={back} onNext={next} />;
      break;
    case 4:
      body = <EvidenceStep nav={nav} back={back} onNext={next} />;
      break;
    case 5:
      body = <MediaStep nav={nav} back={back} onNext={next} />;
      break;
    case 6:
      body = <ToolsStep brandId={brandId} nav={nav} back={back} onNext={() => void finishTools()} />;
      break;
    default:
      body = <DoneStep brandId={brandId} nav={nav} back={back} />;
  }

  return (
    <Page>
      {flowError && <p role="alert" className="text-sm text-danger">{flowError}</p>}
      <div key={current}>{body}</div>
    </Page>
  );
}

/** Prototype `.wrap`: the flow's content is at most 1180px wide. */
function Page({ children }: { children: ReactNode }) {
  return <div className="flex max-w-[1180px] flex-col gap-4">{children}</div>;
}

/** Only explicit wizard steps are valid URL positions. */
function parseStepParam(raw: string | null): number | null {
  if (raw === null) return null;
  const n = Number(raw);
  if (!Number.isInteger(n) || n < 1 || n > LAST_STEP) return null;
  return n;
}
