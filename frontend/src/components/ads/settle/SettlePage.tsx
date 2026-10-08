import { isRejected } from "@/lib/http";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { Skeleton } from "@/components/layout/Skeleton";
import { getSettle, writeSettle, type SettleView } from "@/lib/adsSettleApi";
import { getQueue, type QueuePayload } from "@/lib/adsTriageApi";
import { fetchActiveJobs } from "@/lib/jobsApi";
import { Chip, Disclosure, FlowHeader, ReadFailed, useAdsRules, type FlowStep } from "../patterns";
import { decisionHref } from "../home/QueueRow";
import { homeBoard } from "../home/TodayDecisions";
import { settlePosition } from "../home/status";
import { SettleAngles, angleOf, learnRows, type AnglePick, type AnglePicks, type JobsRead } from "./SettleAngles";
import { SettleNote } from "./SettleNote";
import { SettleResult } from "./SettleResult";
import { FROM_META, isImported, settleRule } from "./settleCsv";
import { NextPeriodSources } from "./NextPeriodSources";

/** F29-I12: the three-step period settle 這期成績 → 確認每則主打什麼 → 寫進筆記本 (prototype v10 `stepRes()`,
 * `stepAngle()`, `stepNote()`; Feature F29 Contract E). One period is one calendar month. The page reads
 * `GET …/settle?month=` once and keeps the picks across the three steps; the only write is the one POST on
 * step 3. While an AI angle job is pending it re-reads the settle and the job queue every few seconds.
 * F32-I02: the step is the `?step=` query, not a path segment — `AppShell` re-keys the page on the pathname, so a
 * path step remounted the page between steps and lost the picks; a query change keeps it mounted. */

export type SettleStep = "result" | "angle" | "note";
const STEPS: SettleStep[] = ["result", "angle", "note"];
const POLL_MS = 3000;

export const isSettleStep = (value: string | undefined): value is SettleStep => STEPS.includes(value as SettleStep);

export function settlePath(brandId: string, month: string, step: SettleStep): string {
  return `/brands/${encodeURIComponent(brandId)}/ads/settle/${encodeURIComponent(month)}?step=${step}`;
}

type Read = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; view: SettleView };

export function SettlePage({ brandId, month }: { brandId: string; month: string }) {
  const [searchParams] = useSearchParams();
  const stepParam = searchParams.get("step") ?? undefined;
  const step: SettleStep = isSettleStep(stepParam) ? stepParam : "result";
  const [read, setRead] = useState<Read>({ status: "loading" });
  const [tick, setTick] = useState(0);
  const [picks, setPicks] = useState<AnglePicks>({});
  const [jobs, setJobs] = useState<JobsRead>({ status: "loading" });
  const [queue, setQueue] = useState<QueuePayload | null>(null);
  const [busy, setBusy] = useState(false);
  const [writeError, setWriteError] = useState<string | null>(null);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const readEpoch = useRef(0);
  const rule = settleRule(useAdsRules());

  const homeHref = `/brands/${encodeURIComponent(brandId)}/ads`;
  const path = (s: SettleStep) => {
    const query = new URLSearchParams(searchParams);
    query.set("step", s);
    return `${settlePath(brandId, month, s).split("?")[0]}?${query}`;
  };

  // The settle read; a re-read keeps the last view on screen (a failed poll never blanks the page).
  useEffect(() => {
    const controller = new AbortController();
    const epoch = ++readEpoch.current;
    getSettle(brandId, month, controller.signal)
      .then((view) => {
        if (controller.signal.aborted || readEpoch.current !== epoch) return;
        setRead({ status: "ready", view });
        setRefreshError(null);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted || readEpoch.current !== epoch) return;
        setRefreshError(error instanceof Error ? error.message : "讀取失敗");
        setRead((prev) => (prev.status === "ready" ? prev : { status: "error", message: error instanceof Error ? error.message : "讀取失敗" }));
      });
    return () => controller.abort();
  }, [brandId, month, tick]);

  useEffect(() => {
    let cancelled = false;
    getQueue(brandId).then((q) => { if (!cancelled) setQueue(q); }).catch(() => {});
    return () => { cancelled = true; };
  }, [brandId]);

  const view = read.status === "ready" ? read.view : null;
  const pending = !!view && learnRows(view).some((row) => row.angles.status === "pending");

  const readJobs = useCallback(() => {
    fetchActiveJobs().then((snapshot) => setJobs({ status: "ready", snapshot })).catch(() => setJobs({ status: "error" }));
  }, []);

  // While any angle is still being worked on: the queue position now, then the settle and the queue again every few seconds.
  useEffect(() => {
    if (!pending || busy) return;
    readJobs();
    const timer = setTimeout(() => setTick((t) => t + 1), POLL_MS);
    return () => clearTimeout(timer);
  }, [pending, busy, tick, readJobs]);

  const retry = () => {
    if (busy) return;
    if (read.status === "error") setRead({ status: "loading" });
    setTick((t) => t + 1);
    readJobs();
  };
  const pick = (entityId: string, value: AnglePick) => setPicks((prev) => ({ ...prev, [entityId]: value }));

  const write = async () => {
    if (!view) return;
    setBusy(true);
    readEpoch.current += 1;
    setWriteError(null);
    try {
      const body = learnRows(view)
        .filter((row) => !row.written_angle)
        .map((row) => ({ entity_id: row.entity_id, angle: angleOf(row, picks[row.entity_id]) ?? "" }));
      setRead({ status: "ready", view: await writeSettle(brandId, month, body) });
      setRefreshError(null);
    } catch (error) {
      if (isRejected(error, "settle_not_ended")) setTick((t) => t + 1);
      setWriteError(error instanceof Error ? error.message : "目前無法完成，請稍後重試。");
    } finally {
      setBusy(false);
    }
  };

  const crumb = <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "結算上一期" }]} />;
  const frame = (children: ReactNode) => (
    <div className="flex min-h-[calc(100dvh-108px)] flex-col gap-4 xl:min-h-[calc(100dvh-120px)]">{crumb}
      {read.status === "ready" && refreshError && <ReadFailed what={`重新讀取失敗；目前仍是上次成績，選擇都還在（${refreshError}）`} onRetry={retry} />}
      {children}</div>
  );

  // A missing or unknown step is step 1, at its canonical URL.
  if (stepParam !== step) return <Navigate to={path("result")} replace />;

  if (read.status === "loading") {
    return frame(
      <div className="flex max-w-[1260px] flex-col gap-4" aria-busy="true">
        <Skeleton className="h-16 w-80" />
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>,
    );
  }
  if (read.status === "error" || !view) {
    return frame(
      <div className="max-w-[1260px]">
        <ReadFailed what={`這期成績讀不到；筆記本沒有被改動${read.status === "error" ? `（${read.message}）` : ""}`} onRetry={retry} />
      </div>,
    );
  }

  // Step guards: nothing past step 1 before the month ends; a written month shows what was written.
  if (view.status === "not_ended" && step !== "result") return <Navigate to={path("result")} replace />;
  if (view.status === "written" && step === "angle") return <Navigate to={path("note")} replace />;
  if (view.status === "open" && step === "note" && learnRows(view).some((row) => angleOf(row, picks[row.entity_id]) === null)) {
    return <Navigate to={path("angle")} replace />;
  }

  const current = STEPS.indexOf(step);
  const labels = ["這期成績", "確認每則主打什麼", "寫進筆記本"];
  const steps: FlowStep[] = labels.map((label, i) => ({ label, to: i < current ? path(STEPS[i]) : undefined }));
  const campaignCount = new Set(view.rows.map((row) => row.campaign_id)).size;
  const importedCount = view.campaigns.filter((c) => isImported(c.origin) && view.rows.some((row) => row.campaign_id === c.campaign_id)).length;
  // F49 Contract Q: 「第 N 件（共 M 件）」 is the settle row's served `position` among `decisions.open`; 「下一件」 is the
  // first other open decision on the home board (served order).
  const position = view.status === "open" ? settlePosition(brandId, queue) : null;
  const nextHref = (queue ? homeBoard(brandId, queue).open : [])
    .filter((d) => d.kind !== "settle")
    .map((d) => decisionHref(brandId, d))
    .find((href): href is string => !!href) ?? null;

  const header = (title: string, purpose: string, aside?: ReactNode) => (
    <FlowHeader
      steps={steps} current={current} title={title} purpose={purpose} aside={aside}
      context={<>
        <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
          <i aria-hidden="true" className="grid size-5 place-items-center rounded-md bg-chart-spend text-[11px] text-white not-italic">∑</i>
          {campaignCount} 個活動{importedCount > 0 && `・含 ${importedCount} 個${FROM_META}`}
        </span>
        {position && <span>今天要決定的第 {position.pos} 件（共 {position.total} 件）</span>}
      </>}
    />
  );
  const skipCount = view.rows.length - learnRows(view).length;
  const continuation = view.status !== "not_ended" ? <Disclosure label="從這期來源規劃下一期">
    <NextPeriodSources brandId={brandId} month={view.month} />
  </Disclosure> : null;

  if (step === "result") {
    const aside = view.status === "written" ? <Chip tone="ok">✓ 已寫進筆記本</Chip>
      : view.status === "not_ended" ? <Chip tone="warn">這個月還沒結束</Chip> : undefined;
    return frame(
      <SettleResult view={view} header={header("這期成績", "每則廣告對照它所屬活動的上限", aside)}
        homeHref={homeHref} angleHref={path("angle")} noteHref={path("note")} continuation={continuation} />,
    );
  }
  if (step === "angle") {
    return frame(
      <SettleAngles
        view={view} picks={picks} onPick={pick} jobs={jobs} onRetry={retry}
        header={header("確認每則主打什麼", "AI 從文案挑了 3 個說法，第一個是它的建議",
          skipCount > 0 ? <span className="text-sm text-muted-foreground">不記的 {skipCount} 則不用選</span> : undefined)}
        homeHref={homeHref} resultHref={path("result")} noteHref={path("note")}
      />,
    );
  }
  const written = view.status === "written";
  const count = learnRows(view).length;
  return frame(
    <SettleNote
      view={view} picks={picks} busy={busy} error={writeError} onWrite={() => void write()}
      header={written
        ? header("寫進筆記本了", "下一個新活動的策略會先讀這本筆記本")
        : header("寫進筆記本", `確認後一次寫進筆記本 ${count} 條`, rule ? <span className="text-sm text-muted-foreground">{rule}</span> : undefined)}
      homeHref={homeHref} angleHref={path("angle")} continuation={continuation} next={nextHref ? { href: nextHref } : null}
    />,
  );
}
