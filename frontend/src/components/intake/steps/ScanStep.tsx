import { useEffect, useRef, useState } from "react";
import { WorkerStoppedNotice } from "@/components/layout/WorkerStoppedNotice";
import { fetchOnboardingScan, startOnboardingScan, type OnboardingScan } from "@/lib/intakeOnboardingApi";
import { useWorkerHealth } from "@/lib/useWorkerHealth";
import { cn } from "@/lib/utils";
import { BarNext, OnboardingBar, OnboardingStepHead, type BarBack, type StepNav } from "../OnboardingStepHead";
import { IntakeJobRow } from "../shared/IntakeJobRow";

/** How often a running scan is read again. */
const POLL_MS = 1000;

type View =
  /** A request is in flight (entry read, start, retry): the spinner row, no timer. */
  | { kind: "busy" }
  /** The job runs: the spinner row, read again after `POLL_MS`. */
  | { kind: "running"; at: number }
  | { kind: "failed"; message: string | null }
  | { kind: "done"; scan: OnboardingScan };

const errorText = (err: unknown) => (err instanceof Error ? err.message : "處理失敗，請稍後再試。");

/** Brand onboarding #/b2 AI 讀網站 (prototype `R.b2` of `.harness/scratch/prototype/f41-onboarding/index.html`):
 * what the website/photo scan found, as the rows steps 3/4 will pre-fill, and what it did not find — never a
 * decision. On entry the scan is read (`GET …/onboarding/scan`) and started once if it never ran (`POST`); a
 * running scan is read every second. A failed read shows the backend's message with 重試 and lets the user skip
 * to step 3; the head and the bar stay either way. F47 Contract C: while the scan runs and the background worker is
 * stopped, the worker-stopped notice sits under the spinner row; 再檢查一次 re-reads the worker and the scan.
 * F47 Contract F: pages the read could not open are listed with their reason and 「改網址再讀一次」 (back to step 1);
 * nothing read = no 「找到的東西」 card and the bar offers 「跳過，自己填」. A website list changed since the read
 * makes the server report `none`, so returning here starts a new read instead of showing the old one. */
export function ScanStep({ brandId, nav, back, onNext }: { brandId: string; nav: StepNav; back?: BarBack; onNext: () => void }) {
  const [view, setView] = useState<View>({ kind: "busy" });
  const alive = useRef(true);

  function apply(scan: OnboardingScan) {
    if (!alive.current) return;
    if (scan.status === "done") setView({ kind: "done", scan });
    else if (scan.status === "failed") setView({ kind: "failed", message: scan.error });
    // "none" right after a start = the job is queued but not picked up yet: keep reading.
    else setView({ kind: "running", at: Date.now() });
  }

  function fail(err: unknown) {
    if (alive.current) setView({ kind: "failed", message: errorText(err) });
  }

  function start() {
    setView({ kind: "busy" });
    startOnboardingScan(brandId).then(apply, fail);
  }

  useEffect(() => {
    let cancelled = false;
    alive.current = true;
    setView({ kind: "busy" });
    fetchOnboardingScan(brandId).then(
      (scan) => {
        if (cancelled) return;
        if (scan.status === "none") start();
        else apply(scan);
      },
      (err: unknown) => {
        if (!cancelled) fail(err);
      },
    );
    return () => {
      cancelled = true;
      alive.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brandId]);

  useEffect(() => {
    if (view.kind !== "running") return;
    const timer = window.setTimeout(() => {
      fetchOnboardingScan(brandId).then(apply, fail);
    }, POLL_MS);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view]);

  const worker = useWorkerHealth(view.kind === "running", POLL_MS);
  async function recheck() {
    await Promise.all([worker.recheck(), fetchOnboardingScan(brandId).then(apply, fail)]);
  }

  const done = view.kind === "done" ? view.scan : null;
  const readSomething = !!done && (done.pages_read > 0 || done.photos_read > 0);
  const title = done ? doneTitle(done) : "AI 讀網站";
  const purpose = done ? purposeLine(done) : undefined;

  return (
    <div className="flex flex-col gap-4">
      <OnboardingStepHead {...nav} title={title} purpose={purpose} />

      {done ? (
        <>
          {done.pages_failed.length > 0 && <UnreadPages pages={done.pages_failed} onFixUrls={back?.onClick} />}
          {readSomething && (
            <>
              <ScanCard scan={done} />
              <p className="text-[11.5px] text-muted-foreground">
                系統只預填、不替你決定：每一步按「下一步」才算你確認。商品的細節留到「商品建檔」再問。
              </p>
            </>
          )}
        </>
      ) : view.kind === "failed" ? (
        <IntakeJobRow job={{ status: "failed", error: view.message }} runningLabel="正在讀網站…" actions={[{ label: "重試", onClick: start }]} />
      ) : (
        <>
          <IntakeJobRow job={{ status: "running", error: null }} runningLabel="正在讀網站…" actions={[]} />
          {worker.stalled && <WorkerStoppedNotice onRecheck={recheck} />}
        </>
      )}

      <OnboardingBar back={back}>
        {view.kind === "failed" ? (
          <BarNext label="先跳過，自己填" onClick={onNext} />
        ) : done && !readSomething ? (
          <BarNext label="跳過，自己填" onClick={onNext} />
        ) : (
          <BarNext label="開始確認" disabled={!done} onClick={onNext} />
        )}
      </OnboardingBar>
    </div>
  );
}

/** F47 Contract F (drill-10 R1): 「讀完你的網站了」 only when at least one page was read. */
function doneTitle(scan: OnboardingScan): string {
  if (scan.pages_read > 0) return "我讀完你的網站了";
  if (scan.photos_read > 0) return "我看完你的品牌照片了";
  return "網站沒有讀到";
}

/** 「讀了 3 頁網站、2 張品牌照片；…」: a count of zero is left out. Nothing read: what that means for the next steps. */
function purposeLine(scan: OnboardingScan): string {
  if (scan.pages_read === 0 && scan.photos_read === 0) return "下面的網址都讀不到，後面每一步沒有預填，要你自己填";
  const read = [
    scan.pages_read > 0 ? `${scan.pages_read} 頁網站` : "",
    scan.photos_read > 0 ? `${scan.photos_read} 張品牌照片` : "",
  ].filter(Boolean);
  return `${read.length ? `讀了 ${read.join("、")}；` : ""}下面是我找到的，後面每一步會先幫你填好，你確認就好`;
}

/** The pages the read could not open, each with its reason (F47 Contract F), and the exit that fixes it:
 * 「改網址再讀一次」 goes back to step 1's website list; a changed list makes the read start again on return. */
function UnreadPages({ pages, onFixUrls }: { pages: { url: string; reason: string }[]; onFixUrls?: () => void }) {
  return (
    <section data-slot="unread-pages" className="flex flex-col gap-3 rounded-md border border-danger/40 bg-danger/5 p-3 text-sm">
      <p role="alert" className="font-medium text-danger">這 {pages.length} 個網址讀不到：</p>
      <ul className="flex flex-col gap-1.5">
        {pages.map((page) => (
          <li key={page.url} className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-3">
            <span className="[overflow-wrap:anywhere]">{page.url}</span>
            <span className="text-danger">{page.reason}</span>
          </li>
        ))}
      </ul>
      {onFixUrls && (
        <div>
          <button
            type="button"
            onClick={onFixUrls}
            className="rounded-md border border-border bg-card px-3 py-1.5 text-xs font-medium text-foreground hover:border-primary hover:text-primary"
          >
            改網址再讀一次
          </button>
        </div>
      )}
    </section>
  );
}

/** Prototype `.card` 「找到的東西」 with its `.scan` rows: one per found area, then one row joining the areas not
 * found (「媒體報導、銷售數據」). */
function ScanCard({ scan }: { scan: OnboardingScan }) {
  return (
    <section className="rounded-xl border border-border bg-card px-[22px] py-5">
      <div className="mb-3.5 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-[15px] font-semibold">找到的東西</h2>
        <span data-slot="chip" data-tone="ok" className="inline-flex items-center rounded-full bg-zone-ok px-2.5 py-0.5 text-xs font-medium whitespace-nowrap text-success">
          預填 {scan.prefilled} 項
        </span>
      </div>
      <ul data-slot="scan-rows">
        {scan.found.map((row) => (
          <ScanRow key={`found-${row.area}`} area={row.area} text={row.text} tag={row.note ? `✦ 讀到（${row.note}）` : "✦ 讀到"} />
        ))}
        {scan.not_found.length > 0 && (
          <ScanRow area={scan.not_found.join("、")} text="沒找到，後面問你；沒有也沒關係" tag="網站上沒找到" missing />
        )}
      </ul>
    </section>
  );
}

function ScanRow({ area, text, tag, missing = false }: { area: string; text: string; tag: string; missing?: boolean }) {
  return (
    <li className="grid grid-cols-[120px_minmax(0,1fr)_auto] items-center gap-3 border-t border-border py-2.5 text-[13px] first:border-t-0">
      <span className="text-muted-foreground">{area}</span>
      <span className={cn("[overflow-wrap:anywhere]", missing && "text-muted-foreground")}>{text}</span>
      <span
        data-slot="ai-tag"
        data-source={missing ? "none" : "ai"}
        className={cn(
          "inline-flex items-center gap-1 justify-self-end rounded px-1.5 py-px text-[11px] font-semibold whitespace-nowrap",
          missing ? "bg-muted text-muted-foreground" : "bg-accent text-accent-foreground",
        )}
      >
        {tag}
      </span>
    </li>
  );
}
