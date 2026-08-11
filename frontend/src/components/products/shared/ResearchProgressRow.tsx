import { useEffect, useState } from "react";
import type { ResearchJobState } from "@/lib/productsApi";

/** AI 調研背景工作進行中列（契約 S6.29–S6.31）：沿用既有等待頁慣例（`app/ads/routes.py`
 * `_progress_definition_rows()`）——階段文字＋「已等 X 秒／通常範圍 30 到 60 秒」，不做假
 * 進度條。失敗態換成錯誤列＋「知道了」，不像表單錯誤那樣擋住分頁其餘內容（事實清單照常
 * 顯示，這顆只佔分頁頂端一小條）。 */
export function ResearchProgressRow({ job, onDismissFailed }: { job: ResearchJobState; onDismissFailed: () => void }) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (job.status !== "running" && job.status !== "waiting") return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [job.status]);

  if (job.status === "failed") {
    return (
      <div className="flex items-center justify-between gap-3 rounded-md border border-danger/40 bg-danger/5 p-3 text-sm">
        <p className="text-danger">{job.error ?? "AI 調研失敗，請稍後再試一次。"}</p>
        <button
          type="button"
          onClick={onDismissFailed}
          className="shrink-0 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground hover:border-primary hover:text-primary"
        >
          知道了
        </button>
      </div>
    );
  }

  const elapsedSeconds = Math.max(0, Math.round((now - new Date(job.started_at).getTime()) / 1000));
  return (
    <div className="flex items-center gap-2 rounded-md border border-dashed border-border bg-muted/40 p-3 text-sm text-muted-foreground">
      <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-primary" aria-hidden="true" />
      AI 正在調研中：{job.stage}，已等 {elapsedSeconds} 秒（通常範圍 {job.usual_range_text}），可以先離開這頁，完成後收件匣會通知
    </div>
  );
}
