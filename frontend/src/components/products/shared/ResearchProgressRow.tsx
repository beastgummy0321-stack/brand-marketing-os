import { useEffect, useState } from "react";
import { secondsSince } from "@/lib/format";
import type { ActiveResearchJob } from "@/lib/productsApi";

/** AI 調研背景工作進行中列（契約 S6.29–S6.31）：沿用既有等待頁慣例（`app/ads/routes.py`
 * `_progress_definition_rows()`）——階段文字＋「已等 X 秒／通常範圍 30 到 60 秒」，不做假
 * 進度條。F50-I14: takes only the running／waiting shape; with no real start (`started_at` null) the
 * row says what runs and leaves out 「已等 X 秒」 rather than counting from now. */
export function ResearchProgressRow({ job }: { job: ActiveResearchJob }) {
  const [now, setNow] = useState(() => Date.now()); // ELAPSED_OK: waited-seconds counter
  const timed = job.started_at !== null;

  useEffect(() => {
    if (!timed) return;
    const timer = setInterval(() => setNow(Date.now()), 1000); // ELAPSED_OK: waited-seconds counter tick
    return () => clearInterval(timer);
  }, [timed]);

  const elapsedSeconds = secondsSince(job.started_at, now);
  const waited = elapsedSeconds === null ? "" : `已等 ${elapsedSeconds} 秒（通常範圍 ${job.usual_range_text}），`;
  return (
    <div className="flex items-center gap-2 rounded-md border border-dashed border-border bg-muted/40 p-3 text-sm text-muted-foreground">
      <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-primary" aria-hidden="true" />
      AI 正在調研中：{job.stage}，{waited}可以先離開這頁，完成後收件匣會通知
    </div>
  );
}

/** 失敗態：錯誤列＋「知道了」，不像表單錯誤那樣擋住分頁其餘內容（事實清單照常顯示，這顆只
 * 佔分頁頂端一小條）。 */
export function ResearchFailedRow({ error, onDismiss }: { error: string | null; onDismiss: () => void }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border border-danger/40 bg-danger/5 p-3 text-sm">
      <p className="text-danger">{error ?? "AI 調研失敗，請稍後再試一次。"}</p>
      <button
        type="button"
        onClick={onDismiss}
        className="shrink-0 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground hover:border-primary hover:text-primary"
      >
        知道了
      </button>
    </div>
  );
}
