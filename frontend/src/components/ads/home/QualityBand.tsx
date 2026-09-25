import { Button } from "@/components/layout/ui/button";
import { Skeleton } from "@/components/layout/Skeleton";
import type { HomeOverview } from "@/lib/adsHomeApi";
import { GradeBand, MoneyRule, type BandBucket } from "../patterns";
import { monthNumber } from "./MonthMoney";

/** Home money-quality band (prototype v10 `homeBand()`, `.bandc`): how much of the month's one 已花 figure landed in
 * each grade. `quality.buckets` sum to `spent` exactly (F28-I06); `null` quality means the spend is not fully known
 * (or the block failed) and nothing is graded — said once, never drawn as 0. */
export function QualityBand({ state, onRetry }: {
  state: { status: "loading" } | { status: "error" } | { status: "ready"; home: HomeOverview };
  onRetry: () => void;
}) {
  return (
    <section aria-label="廣告費花得划不划算" className="surface flex flex-col gap-4 px-7 py-6">
      {state.status === "loading" && <><Skeleton className="h-10 w-72" /><Skeleton className="h-32 w-full" /></>}
      {state.status === "error" && (
        <div className="flex flex-wrap items-center gap-3">
          <p role="alert" className="text-sm text-muted-foreground">分級暫時讀取不到</p>
          <Button variant="outline" size="sm" onClick={onRetry}>重新讀取</Button>
        </div>
      )}
      {state.status === "ready" && <Band home={state.home} />}
    </section>
  );
}

function Band({ home }: { home: HomeOverview }) {
  const label = `${monthNumber(home.month)} 月已花`;
  if (home.quality === null) {
    return (
      <p className="text-sm text-muted-foreground">
        {home.spent === null ? `${label}還不完整（有一天的花費沒讀到），先不分級` : "分級暫時讀取不到"}
      </p>
    );
  }
  const buckets: BandBucket[] = home.quality.buckets.map((b) => ({
    grade: b.grade, amount: b.amount, count: b.count,
    ads: b.ads.map((a) => ({ entity_id: a.entity_id, name: a.name ?? "未命名廣告", thumbnail_url: a.thumbnail_url, spend: a.spend })),
  }));
  const cap = home.money?.cap && home.money.cap.basis ? { value: home.money.cap.value, basis: home.money.cap.basis } : null;
  // v10 `moneyRule()` closes the band: 有賺／在虧 is measured against break-even, the grades against the cap.
  return (
    <>
      <GradeBand buckets={buckets} spent={home.spent} spentLabel={label} cap={cap} />
      <MoneyRule breakEven={home.money?.cap?.break_even ?? null} />
    </>
  );
}
