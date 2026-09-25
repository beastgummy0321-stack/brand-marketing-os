import { useCallback, useEffect, useId, useRef, useState } from "react";
import {
  ACTIVE_JOB_KIND_LABELS,
  fetchActiveJobs,
  type ActiveJob,
  type ActiveJobsSnapshot,
} from "@/lib/jobsApi";
import { cn } from "@/lib/utils";
import { Button } from "./ui/button";

const POLL_MS = 8000;

type ReadState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; snapshot: ActiveJobsSnapshot };

function Spinner({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-block shrink-0 animate-spin rounded-full border-2 border-chart-soft border-t-primary",
        className,
      )}
    />
  );
}

function Dot({ tone }: { tone: "ok" | "bad" | "idle" }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-block h-2 w-2 shrink-0 rounded-full",
        tone === "ok" && "bg-success",
        tone === "bad" && "bg-danger",
        tone === "idle" && "bg-grade-thin",
      )}
    />
  );
}

function label(job: ActiveJob): string {
  return ACTIVE_JOB_KIND_LABELS[job.kind] ?? ACTIVE_JOB_KIND_LABELS.other;
}

function elapsed(seconds: number | null): string {
  if (seconds === null || seconds < 60) return "剛開始";
  return `約 ${Math.round(seconds / 60)} 分`;
}

/** `M/D HH:MM`, browser-local — the same short form the top bar's sync time uses. */
function readAt(iso: string): string {
  const d = new Date(iso);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${String(d.getMonth() + 1).padStart(2, "0")}/${String(d.getDate()).padStart(2, "0")} ${hh}:${mm}`;
}

/** What is happening right now (the first running job; the rest wait), not a bare count. */
function pillText(state: ReadState): { text: string; mark: "spin" | "ok" | "bad" | "idle" } {
  if (state.status === "loading") return { text: "讀取背景工作…", mark: "idle" };
  if (state.status === "error") return { text: "背景工作讀取失敗・點開重試", mark: "bad" };
  const jobs = state.snapshot.data;
  const running = jobs.find((j) => j.status === "running");
  const queued = jobs.filter((j) => j.status === "queued");
  if (running) {
    return {
      text: queued.length ? `正在${label(running)}・還有 ${queued.length} 件排隊` : `正在${label(running)}`,
      mark: "spin",
    };
  }
  if (queued.length) {
    const ahead = queued[0].position - 1;
    return { text: `${label(queued[0])}排隊中・前面還有 ${ahead} 件`, mark: "spin" };
  }
  return { text: "沒有背景工作在跑", mark: "ok" };
}

function JobRow({ job, onPick }: { job: ActiveJob; onPick: () => void }) {
  const ahead = job.position - 1;
  return (
    <li className="border-t border-border">
      {/* B0-16: action_url is a full `/app/...` path from the backend, so a plain <a>, not a
       * react-router <Link> (which would prepend the `/app` basename a second time). */}
      <a
        href={job.action_url}
        onClick={onPick}
        className="grid grid-cols-[22px_minmax(0,1fr)_auto] items-center gap-2.5 py-2.5 text-[13px] hover:text-primary"
      >
        {job.status === "running" ? (
          <Spinner className="h-4 w-4" />
        ) : (
          <i
            aria-label={`第 ${job.position} 個`}
            className="grid h-5 w-5 place-items-center rounded-full bg-muted text-[10.5px] font-bold not-italic text-muted-foreground"
          >
            {job.position}
          </i>
        )}
        <span className="min-w-0 [overflow-wrap:anywhere]">
          {label(job)}・{job.brand_name}
        </span>
        <span className="whitespace-nowrap text-[11.5px] text-muted-foreground">
          {job.status === "running"
            ? `進行中・${elapsed(job.waited_seconds)}`
            : ahead > 0
              ? `前面還有 ${ahead} 件`
              : "下一個就輪到"}
        </span>
      </a>
    </li>
  );
}

function ReadFailedBox({ onRetry }: { onRetry: () => void }) {
  return (
    <div role="alert" className="flex items-center gap-4 rounded-lg bg-zone-over px-5 py-4">
      <span
        aria-hidden="true"
        className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-danger text-xl font-bold text-white"
      >
        !
      </span>
      <div className="min-w-0 grow">
        <p className="text-[17px] font-semibold">讀取失敗</p>
        <p className="mt-0.5 text-xs text-muted-foreground">排隊狀態讀不到；工作本身沒有停，做好的結果都在</p>
      </div>
      <Button type="button" variant="outline" size="sm" onClick={onRetry}>
        重試
      </Button>
    </div>
  );
}

/** Top-bar background-work pill and panel (F29-I05, feature Contract G; prototype v10
 * `topRight()`/`renderJobs()`). Polls `GET /api/jobs/active`, which reads the job queue itself:
 * every item has its place in the whole queue (running first), other organisations' jobs are
 * only a number. A failed read is its own state with 重試 — never shown as "nothing running".
 * Read-only: rows only link to the screen the job belongs to. Layout primitives only (the
 * shell may not import the ads kit). */
export function ActiveJobsBell() {
  const [state, setState] = useState<ReadState>({ status: "loading" });
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const pillRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const alive = useRef(true);

  const load = useCallback(() => {
    fetchActiveJobs()
      .then((snapshot) => alive.current && setState({ status: "ready", snapshot }))
      .catch(() => alive.current && setState({ status: "error" }));
  }, []);

  useEffect(() => {
    alive.current = true;
    load();
    const timer = setInterval(load, POLL_MS);
    return () => {
      alive.current = false;
      clearInterval(timer);
    };
  }, [load]);

  const close = useCallback((refocus: boolean) => {
    setOpen(false);
    if (refocus) pillRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
    function onMouseDown(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) close(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") close(true);
    }
    document.addEventListener("mousedown", onMouseDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onMouseDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, close]);

  const pill = pillText(state);

  return (
    <div ref={rootRef} className="relative min-w-0">
      <button
        ref={pillRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={panelId}
        aria-haspopup="dialog"
        title={pill.text}
        className="inline-flex max-w-full items-center gap-[7px] rounded-full border border-border bg-card px-3 py-1 text-[12.5px] text-muted-foreground hover:border-primary hover:text-primary"
      >
        {pill.mark === "spin" ? <Spinner className="h-2.5 w-2.5" /> : <Dot tone={pill.mark} />}
        <span className="min-w-0 truncate">{pill.text}</span>
        <span aria-hidden="true">›</span>
      </button>
      {open && (
        <div
          id={panelId}
          role="dialog"
          aria-label="背景工作"
          className="absolute right-0 top-full z-50 mt-2 w-[380px] max-w-[calc(100vw-24px)] rounded-xl border border-border bg-card px-4 py-3.5 text-sm shadow-[0_14px_36px_rgb(32_34_55/.16)]"
        >
          <div className="mb-1 flex items-center justify-between">
            <b className="font-semibold">背景工作</b>
            <Button ref={closeRef} type="button" variant="ghost" size="xs" onClick={() => close(true)}>
              關閉
            </Button>
          </div>
          {state.status === "error" ? (
            <ReadFailedBox onRetry={load} />
          ) : state.status === "loading" ? (
            <p className="py-3 text-[13px] text-muted-foreground">讀取中…</p>
          ) : (
            <>
              <p className="mb-1.5 mt-0.5 text-[11.5px] text-muted-foreground">
                排隊 {state.snapshot.total} 件・讀取於 {readAt(state.snapshot.generated_at)}
                {state.snapshot.other_count > 0 && `（其中 ${state.snapshot.other_count} 件是系統或其他帳號的工作）`}
              </p>
              {state.snapshot.data.length === 0 ? (
                <p className="border-t border-border py-3 text-[13px] text-muted-foreground">目前沒有你的背景工作在跑。</p>
              ) : (
                <ul>
                  {state.snapshot.data.map((job) => (
                    <JobRow key={`${job.task_name}:${job.position}`} job={job} onPick={() => close(false)} />
                  ))}
                </ul>
              )}
              <p className="mt-2 text-[11.5px] text-muted-foreground">
                今天做完 {state.snapshot.done_today} 件・失敗 {state.snapshot.failed_today} 件
              </p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
