import { Link } from "react-router-dom";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import {
  ACTIVE_JOB_KIND_LABELS,
  fetchActiveJobs,
  workerHealthState,
  type ActiveJob,
  type ActiveJobsSnapshot,
} from "@/lib/jobsApi";
import { formatInstant, useOrgClock } from "@/lib/orgClock";
import { cn } from "@/lib/utils";
import { Button } from "./ui/button";
import { WorkerStoppedNotice } from "./WorkerStoppedNotice";

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

/** What is happening right now (the first running job; the rest wait), not a bare count.
 * Segments marked `wide` only show from `xl` (1280) up: at 1024 the top bar also carries the
 * sync status and the org menu, so the pill drops 「正在」/「還有」 instead of cutting off the count
 * (`title` keeps the full sentence). */
type Segment = { text: string; wide?: boolean };
type Pill = { parts: Segment[]; mark: "spin" | "ok" | "bad" | "idle" };

function pillText(state: ReadState): Pill {
  if (state.status === "loading") return { parts: [{ text: "讀取背景工作…" }], mark: "idle" };
  if (state.status === "error") {
    return { parts: [{ text: "背景工作讀取失敗" }, { text: "・點開重試", wide: true }], mark: "bad" };
  }
  // F47 Contract C: with the worker stopped nothing runs and nothing moves up — say that, not
  // 「排隊中・前面還有 0 件」.
  const health = workerHealthState(state.snapshot);
  if (health !== "alive") {
    if (health === "stopped" && state.snapshot.stalled === true) {
      return { parts: [{ text: "背景程式停了" }, { text: "・工作還排著", wide: true }], mark: "bad" };
    }
    return { parts: [{ text: health === "stopped" ? "背景程式停了" : "背景程式狀態無法確認" }], mark: "bad" };
  }
  const jobs = state.snapshot.data;
  const running = jobs.find((j) => j.status === "running");
  const queued = jobs.filter((j) => j.status === "queued");
  if (running) {
    const parts: Segment[] = [{ text: "正在", wide: true }, { text: label(running) }];
    if (queued.length) parts.push({ text: "・" }, { text: "還有 ", wide: true }, { text: `${queued.length} 件排隊` });
    return { parts, mark: "spin" };
  }
  if (queued.length) {
    const ahead = queued[0].position - 1;
    return {
      parts: [{ text: `${label(queued[0])}排隊中・` }, { text: "前面還有 ", wide: true }, { text: `${ahead} 件` }],
      mark: "spin",
    };
  }
  return { parts: [{ text: "沒有背景工作在跑" }], mark: "ok" };
}

function JobRow({ job, onPick, health }: { job: ActiveJob; onPick: () => void; health: "alive" | "stopped" | "unknown" }) {
  const ahead = job.position - 1;
  return (
    <li className="border-t border-border">
      <Link
        to={job.action_url}
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
          {health !== "alive" ? (health === "stopped" ? "等待背景程式恢復" : "執行狀態待確認") : job.status === "running"
            ? `進行中・${elapsed(job.waited_seconds)}`
            : ahead > 0
              ? `前面還有 ${ahead} 件`
              : "下一個就輪到"}
        </span>
      </Link>
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
        <p className="mt-0.5 text-xs text-muted-foreground">排隊狀態讀不到，還不能確認背景工作是否繼續；已填的資料保留</p>
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
  const clock = useOrgClock();
  const [state, setState] = useState<ReadState>({ status: "loading" });
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const pillRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const alive = useRef(true);

  const load = useCallback(
    () =>
      fetchActiveJobs()
        .then((snapshot) => {
          if (alive.current) setState({ status: "ready", snapshot });
        })
        .catch(() => {
          if (alive.current) setState({ status: "error" });
        }),
    [],
  );

  useEffect(() => {
    alive.current = true;
    void load();
    const timer = setInterval(() => void load(), POLL_MS);
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
  const pillLabel = pill.parts.map((p) => p.text).join("");

  return (
    <div ref={rootRef} className="relative min-w-0 shrink-0 xl:shrink">
      <button
        ref={pillRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={panelId}
        aria-haspopup="dialog"
        title={pillLabel}
        aria-label={pillLabel}
        className="inline-flex max-w-full items-center gap-[7px] rounded-full border border-border bg-card px-3 py-1 text-[12.5px] text-muted-foreground hover:border-primary hover:text-primary"
      >
        {pill.mark === "spin" ? <Spinner className="h-2.5 w-2.5" /> : <Dot tone={pill.mark} />}
        <span className="min-w-0 truncate whitespace-nowrap">
          {pill.parts.map((part, i) => (
            <span key={i} className={part.wide ? "hidden xl:inline" : undefined}>
              {part.text}
            </span>
          ))}
        </span>
        <span aria-hidden="true" className="shrink-0">›</span>
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
            <ReadFailedBox onRetry={() => void load()} />
          ) : state.status === "loading" ? (
            <p className="py-3 text-[13px] text-muted-foreground">讀取中…</p>
          ) : (
            <>
              {workerHealthState(state.snapshot) !== "alive" && (
                <div className="my-2">
                  <WorkerStoppedNotice state={workerHealthState(state.snapshot)} onRecheck={load} />
                </div>
              )}
              <p className="mb-1.5 mt-0.5 text-[11.5px] text-muted-foreground">
                排隊 {state.snapshot.total} 件・讀取於 {formatInstant(state.snapshot.generated_at, clock.timezone, "md_hm")}
                {state.snapshot.other_count > 0 && `（其中 ${state.snapshot.other_count} 件是系統或其他帳號的工作）`}
              </p>
              {state.snapshot.data.length === 0 ? (
                <p className="border-t border-border py-3 text-[13px] text-muted-foreground">目前沒有你的背景工作在跑。</p>
              ) : (
                <ul>
                  {state.snapshot.data.map((job) => (
                    <JobRow key={`${job.task_name}:${job.position}`} job={job} onPick={() => close(false)} health={workerHealthState(state.snapshot)} />
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
