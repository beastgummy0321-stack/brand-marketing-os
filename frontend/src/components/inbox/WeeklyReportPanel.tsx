import { useEffect, useState, type ReactNode } from "react";
import { X } from "lucide-react";
import { EmptyState } from "@/components/layout/EmptyState";
import { SidePanel } from "@/components/layout/SidePanel";
import { Skeleton } from "@/components/layout/Skeleton";
import { formatCurrency } from "@/lib/format";
import { fetchWeeklyReport, type WeeklyReportData } from "@/lib/weeklyApi";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; report: WeeklyReportData };

/** 收件匣內原地開的四件事週報；四行資料全由後端既有來源組裝，沒有圖表。 */
export function WeeklyReportPanel({
  brandId,
  onClose,
  onOpenProposal,
}: {
  brandId: string;
  onClose: () => void;
  onOpenProposal: (proposalId: string) => void;
}) {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  function load() {
    setState({ status: "loading" });
    fetchWeeklyReport(brandId)
      .then((report) => setState({ status: "ready", report }))
      .catch((error: unknown) => setState({
        status: "error",
        message: error instanceof Error ? error.message : "讀取失敗，請稍後再試。",
      }));
  }

  useEffect(load, [brandId]);

  let content: ReactNode;
  if (state.status === "loading") {
    content = <div className="flex flex-col gap-3">{Array.from({ length: 4 }, (_, index) => <Skeleton key={index} className="h-14" />)}</div>;
  } else if (state.status === "error") {
    content = <EmptyState title="讀取失敗" description={state.message} onAction={load} actionLabel="重試" />;
  } else {
    const report = state.report;
    if (report.status === "ready") {
      content = (
        <div className="flex flex-col gap-3 text-sm">
          <p className="text-muted-foreground">{report.week_start} 至 {report.week_end}</p>
          <ReportRow label="這週花了" value={formatCurrency(report.spend)} />
          <ReportRow label="收到訂單" value={`${report.orders} 筆・${formatCurrency(report.revenue)}`} />
          <ReportRow label="值得保留" value={report.keep} />
          <div className="rounded-md border border-border p-3">
            <p className="font-medium text-foreground">下週只改一件事</p>
            <p className="mt-1 text-sm text-foreground">{report.primary_copy}</p>
            <button type="button" onClick={() => onOpenProposal(report.primary_proposal_id)} className="mt-3 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground">
              去核可
            </button>
          </div>
          {report.other_count > 0 && (
            <button type="button" onClick={() => onOpenProposal(report.other_proposal_ids[0])} className="self-start text-sm font-medium text-primary hover:underline">
              其他建議（{report.other_count}）
            </button>
          )}
        </div>
      );
    } else if (report.status === "empty") {
      content = <p className="rounded-md border border-dashed border-border p-5 text-center text-sm text-muted-foreground">這一週還沒開始投放，沒有報告。</p>;
    } else {
      content = <p className="rounded-md border border-warning/30 bg-warning/10 p-4 text-sm text-warning">這週資料還沒補齊，補齊後會自動整理報告。</p>;
    }
  }

  return (
    <SidePanel ariaLabel="本週報告" onClose={onClose} widthClassName="w-[34rem]">
      <div className="flex items-start justify-between gap-3 border-b border-border pb-4">
        <h2 className="font-display text-lg text-foreground">本週報告</h2>
        <button type="button" onClick={onClose} aria-label="關閉側板" className="rounded-md p-2 text-muted-foreground hover:bg-muted">
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
      {content}
    </SidePanel>
  );
}

function ReportRow({ label, value }: { label: string; value: string }) {
  return <div className="rounded-md border border-border p-3"><p className="font-medium text-foreground">{label}</p><p className="mt-1 text-foreground">{value}</p></div>;
}
