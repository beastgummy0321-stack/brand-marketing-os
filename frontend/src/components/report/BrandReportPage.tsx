import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import {
  fetchBrandReport,
  generateBrandReport,
  type BrandReportResponse,
} from "@/lib/brandReportApi";

type PageState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: BrandReportResponse };

const POLL_MS = 8000;

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : "操作失敗，請稍後再試。";
}

function dateLabel(value: string): string {
  return value.slice(0, 10);
}

function costLabel(cost: number | null): string | null {
  return cost === null ? null : `這份報告花了 NT$${cost.toFixed(2)}`;
}

export function BrandReportPage({ brandId }: { brandId: string }) {
  const [state, setState] = useState<PageState>({ status: "loading" });
  const [params, setParams] = useSearchParams();
  const requestedChapter = Number(params.get("chapter") ?? "1") - 1;
  const sectionCount = state.status === "ready" ? state.data.report?.sections.length ?? 0 : 0;
  const chapter = Number.isInteger(requestedChapter) && requestedChapter >= 0 && requestedChapter < sectionCount ? requestedChapter : 0;
  function setChapter(index: number) { setParams(previous => {const next = new URLSearchParams(previous);next.set("chapter",String(index+1));return next;}); }

  const [creating, setCreating] = useState(false);

  const load = useCallback(() => {
    fetchBrandReport(brandId)
      .then((data) => {
        setState({ status: "ready", data });
        setCreating(data.job.status === "running");
      })
      .catch((err: unknown) => setState({ status: "error", message: errorMessage(err) }));
  }, [brandId]);

  useEffect(() => {
    load();
  }, [load]);

  const isRunning = state.status === "ready" && state.data.job.status === "running";

  useEffect(() => {
    if (!isRunning) return undefined;
    const timer = window.setInterval(load, POLL_MS);
    return () => window.clearInterval(timer);
  }, [isRunning, load]);

  function startGeneration() {
    setCreating(true);
    generateBrandReport(brandId)
      .then(load)
      .catch((err: unknown) => {
        setCreating(false);
        setState({ status: "error", message: errorMessage(err) });
      });
  }

  const disabled = creating || isRunning;
  const report = state.status === "ready" ? state.data.report : null;
  const failure = state.status === "ready" && state.data.job.status === "failed" ? state.data.job.message : null;

  return (
    <div className="flex flex-col gap-4">
      <style>{`@media print { .report-print-hidden { display: none !important; } .report-print-page { max-width: none !important; } .report-chapter[hidden] { display: block !important; } .report-reader { display: block !important; } }`}</style>
      <div className="report-print-hidden">
        <Breadcrumb items={[{ label: "品牌總覽", href: "/" }, { label: "顧問分析報告" }]} />
      </div>
      <div className="report-print-page flex flex-col gap-4">
        <header className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="font-display text-3xl text-foreground">顧問分析報告</h1>
            {isRunning && <p className="mt-1 text-sm text-muted-foreground">正在整理五章，完成後會自動更新。</p>}
          </div>
          <div className="report-print-hidden flex gap-2">
            <button
              type="button"
              onClick={startGeneration}
              disabled={disabled}
              className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {disabled ? "生成中…" : "重新生成報告"}
            </button>
            <button
              type="button"
              onClick={() => window.print()}
              className="rounded-md border border-border bg-card px-3 py-1.5 text-sm font-medium text-foreground hover:bg-muted"
            >
              列印／存成 PDF
            </button>
          </div>
        </header>

        {state.status === "loading" && <EmptyState title="讀取中…" description="正在讀取顧問分析報告。" />}
        {state.status === "error" && (
          <EmptyState title="讀取失敗" description={state.message} actionLabel="重新載入" onAction={load} />
        )}
        {failure && <p className="rounded-md border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">{failure}</p>}
        {state.status === "ready" && !report && (
          <EmptyState
            title="這個品牌還沒有顧問分析報告"
            description="報告會把已確認的品牌事實整理成一份給人讀的分析，包含定位、市場觀察、可用宣稱與節奏方向。"
            actionLabel={disabled ? "生成中…" : "生成報告"}
            actionDisabled={disabled}
            onAction={startGeneration}
          />
        )}
        {report && (
          <article className="flex flex-col gap-4">
            <p className="text-sm text-muted-foreground">
              {[
                `生成日期 ${dateLabel(report.generated_at)}`,
                `依據第 ${report.brand_version} 版品牌資料`,
                report.model,
                costLabel(report.cost),
              ]
                .filter(Boolean)
                .join("・")}
            </p>
            {report.staleness && (
              <p className="rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">{report.staleness}</p>
            )}
            {report.thin_data && (
              <p className="rounded-md border border-blue-300 bg-blue-50 px-4 py-3 text-sm text-blue-900">
                資料尚少，這份報告多半是推論，建議先補充品牌事實再重新生成。
              </p>
            )}
            <div className="workspace-split report-reader"><nav className="workspace-subnav report-print-hidden" aria-label="報告章節">{report.sections.map((section,index) => <button key={section.label} aria-pressed={chapter===index} onClick={() => setChapter(index)}><span className="text-xs text-muted-foreground">{String(index+1).padStart(2,"0")}</span>{section.label}</button>)}</nav><div className="min-w-0">
            {report.sections.map((section,index) => (
              <section key={section.label} hidden={chapter!==index} className="report-chapter rounded-[var(--radius-xl)] border border-border bg-card p-5 shadow-[var(--shadow-card)]">
                <h2 className="font-display text-xl text-foreground">{section.label}</h2>
                <p className="mt-3 leading-7 text-foreground">{section.summary}</p>
                {section.points.length > 0 && (
                  <ul className="mt-3 flex list-disc flex-col gap-1 pl-5 text-sm leading-6 text-foreground">
                    {section.points.map((point, index) => <li key={`${section.label}-${index}`}>{point}</li>)}
                  </ul>
                )}
              </section>
            ))}
            </div></div>
          </article>
        )}
      </div>
    </div>
  );
}
