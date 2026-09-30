import { useEffect, useState } from "react";

/** What the row reads of a background job. The legacy intake jobs (`IntakeJobState`) carry the stage and timing;
 * the onboarding scan (`OnboardingScan`, F42-I07) carries only status and error, so its running row is the label
 * alone. */
export interface IntakeJobRowState {
  status: string;
  error: string | null;
  stage?: string;
  started_at?: string;
  usual_range_text?: string;
}

/** 三種背景工作進行中／失敗列共用（契約 S4.14/16、S4.25/31、S4.53/55），樣式沿用
 * `products/shared/ResearchProgressRow.tsx` 的既有慣例（等待動畫、已等 X 秒／通常範圍）。
 * 跟那顆元件不同的地方只有一點：三步失敗態要的動作按鈕數量不一樣（3～4 顆，各自文字不同），
 * `ResearchProgressRow` 寫死「知道了」單一按鈕，這裡改成可配置陣列。 */
export function IntakeJobRow({
  job,
  runningLabel,
  actions,
}: {
  job: IntakeJobRowState;
  runningLabel: string;
  actions: { label: string; onClick: () => void }[];
}) {
  const [now, setNow] = useState(() => Date.now());
  const timed = job.started_at !== undefined;

  useEffect(() => {
    if (!timed || (job.status !== "running" && job.status !== "waiting")) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [job.status, timed]);

  if (job.status === "failed") {
    return (
      <div className="flex flex-col gap-3 rounded-md border border-danger/40 bg-danger/5 p-3 text-sm">
        <p role="alert" className="text-danger">{job.error ?? "AI 呼叫失敗，請稍後再試一次。"}</p>
        <div className="flex flex-wrap gap-2">
          {actions.map((a) => (
            <button
              key={a.label}
              type="button"
              onClick={a.onClick}
              className="rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground hover:border-primary hover:text-primary"
            >
              {a.label}
            </button>
          ))}
        </div>
      </div>
    );
  }

  const elapsedSeconds = timed ? Math.max(0, Math.round((now - new Date(job.started_at as string).getTime()) / 1000)) : 0;
  return (
    <div role="status" className="flex items-center gap-2 rounded-md border border-dashed border-border bg-muted/40 p-3 text-sm text-muted-foreground">
      <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-primary" aria-hidden="true" />
      {timed
        ? `${runningLabel}：${job.stage ?? ""}，已等 ${elapsedSeconds} 秒（通常${job.usual_range_text ?? ""}），可以先離開這裡`
        : runningLabel}
    </div>
  );
}
