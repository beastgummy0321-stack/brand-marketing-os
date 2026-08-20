import { useCallback, useEffect, useState } from "react";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import {
  fetchDataOnboarding,
  startGa4Backfill,
  startGa4Sync,
  startMetaBackfill,
  type DataOnboardingResponse,
  type OnboardingItem,
} from "@/lib/dataOnboardingApi";

type PageState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: DataOnboardingResponse };

const POLL_MS = 8000;

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : "操作失敗，請稍後再試。";
}

function jobKey(item: OnboardingItem): "meta_backfill" | "ga4_backfill" | null {
  if (item.key === "meta_claim" && item.action_text.includes("回填")) return "meta_backfill";
  if (item.key === "ga4_backfill" && item.action_text.includes("回填")) return "ga4_backfill";
  return null;
}

function badgeClass(kind: OnboardingItem["badge_kind"]): string {
  if (kind === "ok") return "bg-emerald-100 text-emerald-800";
  if (kind === "warn") return "bg-amber-100 text-amber-900";
  return "bg-muted text-muted-foreground";
}

export function DataOnboardingPage({ brandId }: { brandId: string }) {
  const [state, setState] = useState<PageState>({ status: "loading" });
  const [starting, setStarting] = useState<"meta_backfill" | "ga4_backfill" | "ga4_sync" | null>(null);

  const load = useCallback(() => {
    fetchDataOnboarding(brandId)
      .then((data) => {
        setState({ status: "ready", data });
        setStarting(null);
      })
      .catch((err: unknown) => setState({ status: "error", message: errorMessage(err) }));
  }, [brandId]);

  useEffect(() => {
    load();
  }, [load]);

  const running = state.status === "ready" && Object.values(state.data.data.jobs).some((job) => job.status === "running");
  useEffect(() => {
    if (!running) return undefined;
    const timer = window.setInterval(load, POLL_MS);
    return () => window.clearInterval(timer);
  }, [load, running]);

  function start(kind: "meta_backfill" | "ga4_backfill" | "ga4_sync") {
    setStarting(kind);
    const request = kind === "meta_backfill"
      ? startMetaBackfill(brandId)
      : kind === "ga4_backfill" ? startGa4Backfill(brandId) : startGa4Sync(brandId);
    request.then(load).catch((err: unknown) => {
      setStarting(null);
      setState({ status: "error", message: errorMessage(err) });
    });
  }

  const data = state.status === "ready" ? state.data.data : null;
  const ga4SyncJob = data?.jobs.ga4_sync;

  return (
    <div className="flex flex-col gap-5">
      <Breadcrumb items={[{ label: "跨品牌總覽", href: "/" }, { label: "資料上線" }]} />
      <header>
        <h1 className="font-display text-3xl text-foreground">資料上線</h1>
        <p className="mt-2 text-muted-foreground">把過去的資料接進來，判讀才有比較基準。做完 3 件必要的就夠了。</p>
        {data && <p className="mt-3 text-sm font-medium text-foreground">進度：已完成 {data.progress.done}／{data.progress.total}</p>}
      </header>

      {state.status === "loading" && <EmptyState title="讀取中…" description="正在讀取資料上線狀態。" />}
      {state.status === "error" && <EmptyState title="讀取失敗" description={state.message} actionLabel="重新載入" onAction={load} />}

      {data && (
        <>
          <section className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {data.checklist.map((item) => {
              const key = jobKey(item);
              const job = key ? data.jobs[key] : null;
              const isRunning = job?.status === "running";
              const isStarting = starting === key;
              const failure = job?.status === "failed" ? job.message : null;
              return (
                <article key={item.key} className="rounded-[var(--radius-xl)] border border-border bg-card p-5 shadow-[var(--shadow-card)]">
                  <div className="flex items-start justify-between gap-3">
                    <h2 className="font-display text-xl text-foreground">{item.label}</h2>
                    <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${badgeClass(item.badge_kind)}`}>{item.badge_label}</span>
                  </div>
                  <p className="mt-3 text-sm leading-6 text-muted-foreground">{item.description}</p>
                  {item.baseline && (
                    <dl className="mt-4 flex flex-col gap-1 text-sm text-foreground">
                      {item.baseline.map(([label, value]) => <div key={label} className="flex justify-between gap-4"><dt>{label}</dt><dd>{value === "算不出" ? "累積中" : value}</dd></div>)}
                    </dl>
                  )}
                  {item.baseline_note && <p className="mt-3 text-xs text-muted-foreground">{item.baseline_note}</p>}
                  {failure && <p className="mt-4 rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">{failure}</p>}
                  <div className="mt-5">
                    {key ? (
                      <button type="button" onClick={() => start(key)} disabled={isRunning || isStarting} className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60">
                        {isRunning || isStarting ? "回填中…" : item.action_text}
                      </button>
                    ) : (
                      <a href={item.action_url} className="rounded-md border border-border bg-card px-3 py-1.5 text-sm font-medium text-foreground hover:bg-muted">{item.action_text}</a>
                    )}
                  </div>
                </article>
              );
            })}
          </section>

          <section className="rounded-[var(--radius-xl)] border border-border bg-card p-5 shadow-[var(--shadow-card)]">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div><h2 className="font-display text-xl text-foreground">GA4 同步狀態</h2><p className="mt-1 text-sm text-muted-foreground">需要最新資料時可手動同步。</p></div>
              <button type="button" onClick={() => start("ga4_sync")} disabled={ga4SyncJob?.status === "running" || starting === "ga4_sync"} className="rounded-md border border-border bg-card px-3 py-1.5 text-sm font-medium text-foreground hover:bg-muted disabled:cursor-not-allowed disabled:opacity-60">
                {ga4SyncJob?.status === "running" || starting === "ga4_sync" ? "同步中…" : "同步 GA4"}
              </button>
            </div>
            {ga4SyncJob?.status === "failed" && <p className="mt-3 rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">{ga4SyncJob.message}</p>}
          </section>

          <section className="rounded-[var(--radius-xl)] border border-border bg-card p-5 shadow-[var(--shadow-card)]">
            <h2 className="font-display text-xl text-foreground">成熟門檻</h2>
            <div className="mt-4 overflow-x-auto"><table className="w-full text-left text-sm"><thead className="border-b border-border text-muted-foreground"><tr><th className="pb-2">項目</th><th className="pb-2">目前值</th><th className="pb-2">門檻</th><th className="pb-2">狀態</th></tr></thead><tbody>{data.maturity.rows.map((row) => <tr key={row.label} className="border-b border-border last:border-0"><td className="py-3">{row.label}</td><td className="py-3">{row.value_label === "算不出" ? "累積中" : row.value_label}</td><td className="py-3">{row.threshold_label}</td><td className="py-3"><span className={row.met ? "text-emerald-700" : "text-amber-800"}>{row.met ? "已達成" : "還沒"}</span>{row.gap && <p className="mt-1 text-xs text-muted-foreground">{row.gap}</p>}</td></tr>)}</tbody></table></div>
          </section>
        </>
      )}
    </div>
  );
}
