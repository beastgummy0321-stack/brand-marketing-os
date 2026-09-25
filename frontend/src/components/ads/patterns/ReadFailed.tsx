import { Button } from "@/components/layout/ui/button";

/** v10 `failBox()`: a failed read is its own state, never shown as empty data (Feature F29 Contract K read
 * convention). `what` says what could not be read and what is still safe; `onRetry` re-runs the read.
 * `data-slot="read-failed"`. */
export function ReadFailed({ what, onRetry, retryLabel = "重試" }: { what: string; onRetry?: () => void; retryLabel?: string }) {
  return (
    <div data-slot="read-failed" role="alert" className="flex flex-wrap items-center gap-4 rounded-xl bg-danger/10 px-5 py-4">
      <div aria-hidden="true" className="flex size-11 shrink-0 items-center justify-center rounded-full bg-danger text-xl font-bold text-white">!</div>
      <div className="min-w-[200px] flex-1">
        <b className="text-[17px]">讀取失敗</b>
        <div className="mt-0.5 text-xs text-muted-foreground">{what}</div>
      </div>
      {onRetry && <Button variant="outline" onClick={onRetry}>{retryLabel}</Button>}
    </div>
  );
}
