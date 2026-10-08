import { useState } from "react";
import { Button } from "./ui/button";

/** The one sentence every waiting page shows while the worker is stopped (F47 Contract C). */
const WORKER_STOPPED_TEXT = "這件工作還排著，已填的資料沒丟。重新啟動行銷系統後會自動接著做。";

/** F47 Contract C: shown wherever a page waits on a background job and `GET /api/jobs/active` says
 * `stalled` (the jobs bell, the brand site read, the product-page read, copy generation, a workbench
 * set). The `ReadFailed`-style inline row (alert tone, round mark, one action): what stopped, that
 * the work and the user's data are kept, and how it resumes. 「再檢查一次」 runs `onRecheck` — the
 * caller re-reads both the job state and its own page state — and says so while it runs. Layout
 * primitives only: the shell part may not import a feature kit. */
export function WorkerStoppedNotice({ onRecheck, state = "stopped" }: {
  onRecheck: () => Promise<unknown> | void;
  state?: "alive" | "stopped" | "unknown";
}) {
  const [checking, setChecking] = useState(false);

  async function recheck() {
    setChecking(true);
    try {
      await onRecheck();
    } finally {
      setChecking(false);
    }
  }

  return (
    <div
      data-slot="worker-stopped"
      role="alert"
      className="flex flex-wrap items-center gap-4 rounded-xl bg-danger/10 px-5 py-4"
    >
      <div
        aria-hidden="true"
        className="flex size-11 shrink-0 items-center justify-center rounded-full bg-danger text-xl font-bold text-white"
      >
        !
      </div>
      <p className="min-w-[200px] flex-1 text-[13px] leading-relaxed">
        <b className="text-[15px] font-semibold">{state === "unknown" ? "背景程式狀態無法確認" : "背景程式停了"}</b>：
        {state === "unknown" ? "目前讀不到背景程式狀態，還不能確認工作是否繼續。已填的資料保留，請再檢查一次。" : WORKER_STOPPED_TEXT}
      </p>
      <Button type="button" variant="outline" size="sm" busy={checking} onClick={() => void recheck()}>
        {checking ? "檢查中…" : "再檢查一次"}
      </Button>
    </div>
  );
}
