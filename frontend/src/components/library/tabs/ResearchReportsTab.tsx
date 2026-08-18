import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Pager } from "@/components/layout/Pager";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { usePagination } from "@/lib/usePagination";
import {
  fetchResearchReport,
  fetchResearchReports,
  type ResearchReport,
  type ResearchReportSummary,
} from "@/lib/researchReportApi";

const PAGE_SIZE = 12;

type ListState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; reports: ResearchReportSummary[] };

type ReportState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; report: ResearchReport };

function dateLabel(createdAt: string): string {
  return createdAt.slice(0, 10);
}

function reportError(err: unknown): string {
  return err instanceof Error ? err.message : "讀取失敗，請稍後再試。";
}

/** 第七分頁籤：只讀既有貼回原文，沒有任何改寫或入檔動作。 */
export function ResearchReportsTab({ brandId }: { brandId: string }) {
  const [listState, setListState] = useState<ListState>({ status: "loading" });
  const [reportState, setReportState] = useState<ReportState>({ status: "loading" });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const reports = listState.status === "ready" ? listState.reports : [];
  const pagination = usePagination(reports, PAGE_SIZE);

  const loadReports = useCallback(() => {
    setListState({ status: "loading" });
    setSelectedId(null);
    fetchResearchReports(brandId)
      .then((items) => setListState({ status: "ready", reports: items }))
      .catch((err: unknown) => setListState({ status: "error", message: reportError(err) }));
  }, [brandId]);

  const loadReport = useCallback(
    (draftId: string) => {
      setReportState({ status: "loading" });
      fetchResearchReport(brandId, draftId)
        .then((report) => setReportState({ status: "ready", report }))
        .catch((err: unknown) => setReportState({ status: "error", message: reportError(err) }));
    },
    [brandId],
  );

  useEffect(() => loadReports(), [loadReports]);

  useEffect(() => {
    if (reports.length > 0 && selectedId === null) setSelectedId(reports[0].id);
  }, [reports, selectedId]);

  useEffect(() => {
    if (selectedId) loadReport(selectedId);
  }, [loadReport, selectedId]);

  function choosePage(page: number) {
    pagination.goToPage(page);
    const firstOnPage = reports[(page - 1) * PAGE_SIZE];
    if (firstOnPage) {
      setReportState({ status: "loading" });
      setSelectedId(firstOnPage.id);
    }
  }

  function chooseReport(draftId: string) {
    setReportState({ status: "loading" });
    setSelectedId(draftId);
  }

  let content: ReactNode;
  if (listState.status === "loading") {
    content = (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-10 w-56" />
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  } else if (listState.status === "error") {
    content = (
      <EmptyState
        title="讀取失敗"
        description={listState.message}
        actionLabel="重新載入"
        onAction={loadReports}
      />
    );
  } else if (reports.length === 0) {
    content = (
      <EmptyState
        title="還沒有調研報告"
        description="先到建檔精靈完成一份調研，這裡會保留每次貼回的原文。"
        actionHref={`/brands/${encodeURIComponent(brandId)}/intake`}
        actionLabel="去做調研"
        actionInternal
      />
    );
  } else {
    content = (
      <div ref={pagination.topRef} className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-xl)] border border-border bg-card p-4 shadow-[var(--shadow-card)]">
          <label className="flex items-center gap-2 text-sm font-medium text-foreground">
            選擇日期
            <select
              value={selectedId ?? ""}
              onChange={(event) => chooseReport(event.target.value)}
              className="rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground"
            >
              {pagination.pageItems.map((item) => (
                <option key={item.id} value={item.id}>
                  {dateLabel(item.created_at)}
                  {item.id === reports[0].id ? "（最新）" : ""}
                </option>
              ))}
            </select>
          </label>
          {reportState.status === "ready" && (
            <Link
              to={`/brands/${encodeURIComponent(brandId)}/library?tab=facts&source_draft_id=${encodeURIComponent(reportState.report.id)}`}
              className="rounded-full border border-primary px-3 py-1 text-sm font-medium text-primary hover:bg-primary/10"
            >
              已入檔 {reportState.report.confirmed_count} 條
            </Link>
          )}
        </div>

        {pagination.pageCount > 1 && (
          <Pager
            page={pagination.page}
            pageCount={pagination.pageCount}
            totalCount={pagination.totalCount}
            onChange={choosePage}
          />
        )}

        {reportState.status === "loading" && (
          <div className="flex flex-col gap-3 rounded-[var(--radius-xl)] border border-border bg-card p-4 shadow-[var(--shadow-card)]">
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        )}

        {reportState.status === "error" && selectedId && (
          <EmptyState
            title="讀取失敗"
            description={reportState.message}
            actionLabel="重新載入"
            onAction={() => loadReport(selectedId)}
          />
        )}

        {reportState.status === "ready" && <ReportBody brandId={brandId} report={reportState.report} />}
      </div>
    );
  }

  return <section aria-label="調研報告">{content}</section>;
}

function ReportBody({ brandId, report }: { brandId: string; report: ResearchReport }) {
  function sectionId(index: number): string {
    return `research-report-${report.id}-${index}`;
  }

  function jumpToSection(index: number) {
    const target = document.getElementById(sectionId(index)) as HTMLDetailsElement | null;
    if (target) {
      target.open = true;
      target.scrollIntoView({ block: "start", behavior: "smooth" });
    }
  }

  return (
    <div className="flex flex-col gap-3">
      {report.sections.length > 0 && (
        <div className="flex flex-wrap gap-2" aria-label="跳到報告段落">
          {report.sections.map((section, index) => (
            <button
              key={`${section.title}-${index}`}
              type="button"
              onClick={() => jumpToSection(index)}
              className="rounded-full border border-border bg-card px-3 py-1 text-sm text-muted-foreground hover:border-primary hover:text-primary"
            >
              {section.title}
            </button>
          ))}
        </div>
      )}

      <article className="flex flex-col gap-3 rounded-[var(--radius-xl)] border border-border bg-card p-4 shadow-[var(--shadow-card)]">
        {report.leading_text && <RawText text={report.leading_text} />}
        {report.sections.length === 0 ? (
          <RawText text={report.paste_raw} />
        ) : (
          report.sections.map((section, index) => (
            <details
              key={`${section.title}-${index}`}
              id={sectionId(index)}
              open={index === 0}
              className="rounded-lg border border-border bg-background"
            >
              <summary className="cursor-pointer px-4 py-3 font-display text-base text-foreground">
                {section.title}
              </summary>
              <RawText text={section.raw_text} className="border-t border-border px-4 py-3" />
            </details>
          ))
        )}
      </article>

      <Link
        to={`/brands/${encodeURIComponent(brandId)}/library?tab=facts&source_draft_id=${encodeURIComponent(report.id)}`}
        className="w-fit text-sm font-medium text-primary underline-offset-4 hover:underline"
      >
        查看已入檔內容（{report.confirmed_count} 條）
      </Link>
    </div>
  );
}

function RawText({ text, className = "" }: { text: string; className?: string }) {
  return <pre className={`whitespace-pre-wrap break-words font-sans text-sm leading-6 text-foreground ${className}`}>{text}</pre>;
}
