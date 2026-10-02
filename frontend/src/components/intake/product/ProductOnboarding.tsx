import { useEffect, useRef, useState, type ReactNode } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { EmptyState } from "@/components/layout/EmptyState";
import { WorkerStoppedNotice } from "@/components/layout/WorkerStoppedNotice";
import type { ProductOnboardingStatus, ProductWhat } from "@/lib/intakeProductApi";
import { fetchProductOnboarding, fetchProductWhat, startProductScan } from "@/lib/intakeProductApi";
import { useWorkerHealth } from "@/lib/useWorkerHealth";
import type { BarBack, CrumbItem, StepNav } from "../OnboardingStepHead";
import { IntakeJobRow } from "../shared/IntakeJobRow";
import { productOnboardingPath } from "./ProductCard";
import { ProductDoneStep } from "./ProductDoneStep";
import { ProductEvidenceStep } from "./ProductEvidenceStep";
import { SellWaysStep } from "./SellWaysStep";
import { NewProductStep, WhatStep } from "./WhatStep";
import { WhoStep } from "./WhoStep";

/** Prototype `PSTEPS` of `.harness/scratch/prototype/f41-onboarding/index.html`. */
export const PRODUCT_STEPS = ["商品是什麼", "誰會買", "證據與說法", "賣法與價格", "完成"];
const LAST_STEP = PRODUCT_STEPS.length;
/** How often a running product-page read is read again. */
const POLL_MS = 1500;

const productsPath = (brandId: string) => `/brands/${encodeURIComponent(brandId)}/products`;

/** Prototype `head("p", …)`: 「商品 › 商品建檔 › 〈商品〉」; a product not created yet has no name. */
export function productCrumb(brandId: string, productName: string): CrumbItem[] {
  const name = productName.trim();
  const crumb: CrumbItem[] = [{ label: "商品", to: productsPath(brandId) }, { label: "商品建檔", strong: true }];
  return name ? [...crumb, { label: name }] : crumb;
}

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "notfound" }
  | { status: "ready"; onboarding: ProductOnboardingStatus; what: ProductWhat };

const errorText = (err: unknown) => (err instanceof Error ? err.message : "讀取失敗，請稍後再試。");

/** Product onboarding, five steps (prototype `#/p1`–`#/p5`). `productId === null` is `/brands/:b/products/new`:
 * name + 商品頁網址, 下一步 creates the product and opens its step 1. Otherwise `GET …/onboarding` says where the
 * product is: `?step=N` (1–5) opens that step, else a product being built opens its current step and a finished one
 * step 5. While the product-page read runs, step 1 shows 「正在讀商品頁…」 above its form and reads the status
 * again; a failed read shows its message with 重試 / 自己填. The head never blanks. F47 Contract C: while the read runs
 * and the background worker is stopped, the worker-stopped notice sits under that row; 再檢查一次 re-reads both. */
export function ProductOnboarding({ brandId, productId }: { brandId: string; productId: string | null }) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [state, setState] = useState<LoadState>({ status: "loading" });
  /** 自己填: the failed read's row is put away for this visit. */
  const [scanDismissed, setScanDismissed] = useState(false);
  const alive = useRef(true);

  async function load(): Promise<ProductOnboardingStatus | null> {
    if (!productId) return null;
    try {
      const [onboarding, what] = await Promise.all([fetchProductOnboarding(brandId, productId), fetchProductWhat(brandId, productId)]);
      if (alive.current) setState({ status: "ready", onboarding, what });
      return onboarding;
    } catch (err) {
      if (!alive.current) return null;
      if (err instanceof Error && err.message.includes("找不到")) setState({ status: "notfound" });
      else setState({ status: "error", message: errorText(err) });
      return null;
    }
  }

  useEffect(() => {
    alive.current = true;
    setState({ status: "loading" });
    setScanDismissed(false);
    void load();
    return () => {
      alive.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brandId, productId]);

  const running = state.status === "ready" && state.onboarding.prefill_status === "running";
  useEffect(() => {
    if (!running || !productId) return;
    const timer = window.setTimeout(() => {
      fetchProductOnboarding(brandId, productId).then(
        async (onboarding) => {
          if (onboarding.prefill_status === "running") {
            if (alive.current) setState((s) => (s.status === "ready" ? { ...s, onboarding } : s));
            return;
          }
          // The read ended: its proposals are in the step GETs now.
          const what = await fetchProductWhat(brandId, productId).catch(() => null);
          if (alive.current) setState((s) => (s.status === "ready" ? { ...s, onboarding, what: what ?? s.what } : s));
        },
        (err: unknown) => {
          if (!alive.current) return;
          setState((s) => (s.status === "ready" ? { ...s, onboarding: { ...s.onboarding, prefill_status: "failed", prefill_error: errorText(err) } } : s));
        },
      );
    }, POLL_MS);
    return () => window.clearTimeout(timer);
  }, [running, state, brandId, productId]);
  const worker = useWorkerHealth(running, POLL_MS);

  const back = (label: string, onClick: () => void): BarBack => ({ label, onClick });
  const toProducts = () => navigate(productsPath(brandId));

  if (!productId) {
    return (
      <Page>
        <NewProductStep
          brandId={brandId}
          nav={{ crumb: productCrumb(brandId, ""), steps: PRODUCT_STEPS, current: 1 }}
          back={back("商品", toProducts)}
          onCreated={({ product_id }) => navigate(productOnboardingPath(brandId, product_id))}
        />
      </Page>
    );
  }

  if (state.status === "loading") {
    return <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">讀取中…</div>;
  }
  if (state.status === "notfound") {
    return <EmptyState title="找不到這個商品" description="這個商品可能已經刪除，或你沒有權限查看。" />;
  }
  if (state.status === "error") {
    return <EmptyState title="讀取失敗" description={state.message} onAction={() => void load()} actionLabel="重新載入" />;
  }

  const { onboarding, what } = state;
  const pid = productId;
  const current = parseStepParam(searchParams.get("step")) ?? (onboarding.completed ? LAST_STEP : onboarding.step);
  const reachable = Math.max(onboarding.completed ? LAST_STEP : onboarding.step, current);

  const goTo = (step: number) => navigate(productOnboardingPath(brandId, pid, step));
  /** After a step saved: the status moves on the server first, then the next step opens. */
  const next = (step: number) => async () => {
    await load();
    if (alive.current) goTo(step + 1);
  };
  const stepBack = back(PRODUCT_STEPS[current - 2] ?? "商品", () => goTo(current - 1));

  const nav: StepNav = {
    crumb: productCrumb(brandId, what.name),
    steps: PRODUCT_STEPS,
    current,
    canSelect: (step) => step <= reachable,
    onSelect: goTo,
  };

  function retryScan() {
    setScanDismissed(false);
    setState((s) => (s.status === "ready" ? { ...s, onboarding: { ...s.onboarding, prefill_status: "running", prefill_error: null } } : s));
    startProductScan(brandId, pid).then(
      (fresh) => alive.current && setState((s) => (s.status === "ready" ? { ...s, onboarding: fresh } : s)),
      (err: unknown) =>
        alive.current &&
        setState((s) => (s.status === "ready" ? { ...s, onboarding: { ...s.onboarding, prefill_status: "failed", prefill_error: errorText(err) } } : s)),
    );
  }

  let scanRow: ReactNode = null;
  if (onboarding.prefill_status === "running") {
    scanRow = (
      <>
        <IntakeJobRow job={{ status: "running", error: null }} runningLabel="正在讀商品頁…" actions={[]} />
        {worker.stalled && <WorkerStoppedNotice onRecheck={() => Promise.all([worker.recheck(), load()])} />}
      </>
    );
  } else if (onboarding.prefill_status === "failed" && !scanDismissed) {
    scanRow = (
      <IntakeJobRow
        job={{ status: "failed", error: onboarding.prefill_error }}
        runningLabel="正在讀商品頁…"
        actions={[
          { label: "重試", onClick: retryScan },
          { label: "自己填", onClick: () => setScanDismissed(true) },
        ]}
      />
    );
  }

  let body: ReactNode;
  switch (current) {
    case 1:
      body = (
        <WhatStep
          brandId={brandId}
          productId={pid}
          nav={nav}
          back={back("商品", toProducts)}
          what={what}
          prefillDone={onboarding.prefill_status === "done"}
          above={scanRow}
          onSaved={async (saved) => {
            setState((s) => (s.status === "ready" ? { ...s, what: saved } : s));
            await next(1)();
          }}
        />
      );
      break;
    case 2:
      body = <WhoStep brandId={brandId} productId={pid} nav={nav} back={stepBack} onNext={() => void next(2)()} />;
      break;
    case 3:
      body = <ProductEvidenceStep brandId={brandId} productId={pid} nav={nav} back={stepBack} onNext={() => void next(3)()} />;
      break;
    case 4:
      body = <SellWaysStep brandId={brandId} productId={pid} nav={nav} back={stepBack} onNext={() => void next(4)()} />;
      break;
    default:
      body = <ProductDoneStep brandId={brandId} productId={pid} nav={nav} what={what} completed={onboarding.completed} onGoStep={goTo} />;
  }

  return <Page>{body}</Page>;
}

/** Prototype `.wrap`: the flow's content is at most 1180px wide. */
function Page({ children }: { children: ReactNode }) {
  return <div className="flex max-w-[1180px] flex-col gap-4">{children}</div>;
}

/** `?step=N`: anything but an integer 1..5 reads as not given (a broken parameter opens where the product is). */
function parseStepParam(raw: string | null): number | null {
  if (raw === null) return null;
  const n = Number(raw);
  if (!Number.isInteger(n) || n < 1 || n > LAST_STEP) return null;
  return n;
}
