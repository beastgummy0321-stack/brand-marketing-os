import { cn } from "@/lib/utils";

/** 「約 N 秒／約 N 分」 from seconds; null stays unknown. */
export function waitedText(seconds: number | null | undefined): string | null {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds < 0) return null;
  return seconds < 60 ? `約 ${Math.max(1, Math.round(seconds))} 秒` : `約 ${Math.round(seconds / 60)} 分`;
}

const MAX_CELLS = 12;

/** v10 `waitLine()` (`.waitbox` + `.qv`): one queue-position line for a screen waiting on background work
 * (Feature F29 Contract G: `status`, 1-based `position` over the whole queue, running first; `total`;
 * `waited_seconds`). An unknown position says so — it is never printed as 第 0 件. The cell strip is drawn only
 * when both numbers are known. `data-slot="wait-line"`. */
export function WaitLine({ title, status, position, total, waitedSeconds, note }: {
  title: string;
  status: "running" | "queued" | null;
  position: number | null;
  total: number | null;
  waitedSeconds: number | null;
  /** e.g. 「可以先離開，整理好會出現在首頁待辦」. */
  note?: string;
}) {
  const waited = waitedText(waitedSeconds);
  const known = position !== null && total !== null && position >= 1 && total >= position;
  let line: string;
  if (status === "running") line = `AI 正在處理${known ? `：共 ${total} 件` : ""}${waitedSeconds === 0 ? "・剛開始" : waited ? `・已跑${waited}` : ""}`;
  else if (known) line = `AI 排隊：第 ${position} 件／共 ${total} 件，前面還有 ${position - 1} 件${waitedSeconds === 0 ? "・剛排進來" : waited ? `・已等${waited}` : ""}`;
  else line = `AI 排隊中・排第幾件讀不到${waited ? `・已等${waited}` : ""}`;
  const cells = known && total <= MAX_CELLS ? total : 0;
  return (
    <div data-slot="wait-line" data-variant={status ?? "unknown"} role="status" className="flex flex-wrap items-center gap-3.5 rounded-xl bg-accent px-[18px] py-3.5">
      <span aria-hidden="true" className="inline-block size-4 shrink-0 animate-spin rounded-full border-2 border-chart-soft border-t-primary" />
      <div className="min-w-[200px] flex-1">
        <b>{title}</b>
        <div className="text-xs text-accent-foreground">{line}</div>
        {note && <div className="text-[11.5px] text-muted-foreground">{note}</div>}
      </div>
      {cells > 0 && (
        <div className="flex gap-1" aria-hidden="true">
          {Array.from({ length: cells }, (_, k) => (
            <i key={k} className={cn("h-2 w-[22px] rounded-[3px] border",
              k === (position as number) - 1 ? "border-primary bg-primary" : k === 0 ? "border-chart-soft bg-chart-soft" : "border-border bg-card")} />
          ))}
        </div>
      )}
    </div>
  );
}
