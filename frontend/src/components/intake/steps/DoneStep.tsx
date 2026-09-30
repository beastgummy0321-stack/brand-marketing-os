import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { Skeleton } from "@/components/layout/Skeleton";
import { fetchLaunchReadiness, type LaunchReadiness, type ReadinessItem, type ReadinessState } from "@/lib/adsLaunchApi";
import { completeOnboarding } from "@/lib/intakeOnboardingApi";
import { cn } from "@/lib/utils";
import { OnboardingBar, OnboardingStepHead, type BarBack, type StepNav } from "../OnboardingStepHead";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; readiness: LaunchReadiness };

/** Prototype `.chk i.g/.y/.r`: green ✓, yellow and red !. */
const MARK: Record<ReadinessState, string> = {
  green: "bg-success",
  yellow: "bg-grade-watch",
  red: "bg-danger",
};

/** Prototype `.chip.ok/.warn/.bad`. */
const CHIP: Record<"ok" | "warn" | "bad", string> = {
  ok: "bg-zone-ok text-success",
  warn: "bg-zone-watch text-warning",
  bad: "bg-zone-over text-danger",
};

const OFFERING_KEY = "offering";

/** Brand onboarding #/b7 完成 (prototype `R.b7` of `.harness/scratch/prototype/f41-onboarding/index.html`):
 * entering the step marks onboarding complete once (`POST …/onboarding/complete`, idempotent), then the card
 * 「可以開始投放了嗎」 prints `GET /api/ads/brands/{b}/readiness` verbatim -- one row per item, colour and words from
 * `app/ads/readiness.py`. A red 商品 row carries the one primary action (its `fix_href`, 「建第一個商品 →」 when there is
 * no product); any other row that is not green gets a 「去改」 link to its step. A failed read keeps the head and bar
 * and puts the retry where the rows go. */
export function DoneStep({ brandId, nav, back }: { brandId: string; nav: StepNav; back?: BarBack }) {
  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const [completeError, setCompleteError] = useState<string | null>(null);
  const completed = useRef<string | null>(null);

  function reload() {
    setLoad({ status: "loading" });
    fetchLaunchReadiness(brandId)
      .then((readiness) => setLoad({ status: "ready", readiness }))
      .catch((err: unknown) => setLoad({ status: "error", message: err instanceof Error ? err.message : "讀取可投放檢查表失敗。" }));
  }

  useEffect(() => {
    // Once per brand, also under StrictMode's double effect run.
    if (completed.current === brandId) return;
    completed.current = brandId;
    setCompleteError(null);
    completeOnboarding(brandId).catch((err: unknown) =>
      setCompleteError(err instanceof Error ? err.message : "處理失敗，請稍後再試。"),
    );
  }, [brandId]);

  useEffect(reload, [brandId]);

  return (
    <div className="flex flex-col gap-4">
      <OnboardingStepHead {...nav} title="品牌建好了" purpose="接下來建你要賣的商品；每個商品各建一次" />
      <section data-slot="readiness-card" aria-labelledby="done-readiness-title" className="rounded-xl border border-border bg-card px-[22px] py-5">
        <div className="mb-3.5 flex flex-wrap items-center justify-between gap-3">
          <h2 id="done-readiness-title" className="text-[15px] font-semibold">可以開始投放了嗎</h2>
          {load.status === "ready" && <StateChip readiness={load.readiness} />}
        </div>
        {load.status === "loading" && (
          <div className="flex flex-col gap-2">
            <Skeleton className="h-11" />
            <Skeleton className="h-11" />
            <Skeleton className="h-11" />
          </div>
        )}
        {load.status === "error" && (
          <div className="flex flex-col items-start gap-2">
            <p role="alert" className="text-sm text-danger">{load.message}</p>
            <Button type="button" variant="link" className="h-auto p-0 text-[13px]" onClick={reload}>重新載入</Button>
          </div>
        )}
        {load.status === "ready" && (
          <ul>
            {load.readiness.items.map((item) => <CheckRow key={item.key} item={item} />)}
          </ul>
        )}
      </section>
      {completeError && <p role="alert" className="text-sm text-danger">{completeError}</p>}
      <OnboardingBar back={back}>
        <Button asChild variant="outline" size="lg" className="font-semibold">
          <Link to={`/brands/${encodeURIComponent(brandId)}/products`}>先看商品頁</Link>
        </Button>
      </OnboardingBar>
    </div>
  );
}

/** The worst state as a chip: 「還差商品」 when the 商品 row is red, otherwise the state's wording from the API. */
function StateChip({ readiness }: { readiness: LaunchReadiness }) {
  const offeringRed = readiness.items.some((item) => item.key === OFFERING_KEY && item.state === "red");
  const tone = offeringRed || readiness.state === "yellow" ? "warn" : readiness.state === "red" ? "bad" : "ok";
  return (
    <span
      data-slot="chip"
      data-tone={tone}
      className={cn("inline-flex shrink-0 items-center rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap", CHIP[tone])}
    >
      {offeringRed ? "還差商品" : readiness.primary.label}
    </span>
  );
}

/** Prototype `chk(c, t, d, a)`: mark, label over the reason, the row's action on the right. */
function CheckRow({ item }: { item: ReadinessItem }) {
  const primary = item.key === OFFERING_KEY && item.state === "red";
  return (
    <li data-slot="check-row" data-state={item.state} className="grid grid-cols-[28px_minmax(0,1fr)_auto] items-center gap-3 border-t border-border py-[11px] first:border-t-0">
      <span aria-hidden="true" className={cn("grid size-6 place-items-center rounded-full text-xs font-bold text-white", MARK[item.state])}>
        {item.state === "green" ? "✓" : "!"}
      </span>
      <div className="min-w-0">
        <b className="font-semibold">{item.label}</b>
        <p className="text-[11.5px] text-muted-foreground">{item.reason}</p>
      </div>
      {primary ? (
        <Button asChild className="px-4 font-semibold">
          <Link to={item.fix_href}>{item.fix_label} →</Link>
        </Button>
      ) : item.state !== "green" ? (
        <Link to={item.fix_href} className="text-[13px] font-medium whitespace-nowrap text-primary hover:underline">去改</Link>
      ) : null}
    </li>
  );
}
