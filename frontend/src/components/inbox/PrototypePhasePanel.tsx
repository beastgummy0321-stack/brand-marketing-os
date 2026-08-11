import { useEffect, useState, type ReactNode } from "react";
import { X } from "lucide-react";
import { EmptyState } from "@/components/layout/EmptyState";
import { SidePanel } from "@/components/layout/SidePanel";
import { Skeleton } from "@/components/layout/Skeleton";
import { fetchPrototypePhase, type PrototypePhaseDetail } from "@/lib/inboxApi";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; detail: PrototypePhaseDetail };

/** 「原型階段結束提醒」詳情側板（S2.15–S2.19）：點收件匣該類別項目的「詳情」開啟，不帶
 * 品牌參數（全站單一旗標）。滑出過場沿用既有側板慣例，見
 * `components/workbench/ThemePanel.tsx` 同一套 `entered` 兩幀進場寫法。 */
export function PrototypePhasePanel({ onClose }: { onClose: () => void }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  function load() {
    setState({ status: "loading" });
    fetchPrototypePhase()
      .then((detail) => setState({ status: "ready", detail }))
      .catch((err: unknown) =>
        setState({
          status: "error",
          message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。",
        }),
      );
  }

  useEffect(load, []);

  let content: ReactNode;
  if (state.status === "loading") {
    content = (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-5 w-2/3" />
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-16" />
        ))}
      </div>
    );
  } else if (state.status === "error") {
    content = (
      <EmptyState title="讀取失敗" description={state.message} onAction={load} actionLabel="重試" />
    );
  } else {
    const { detail } = state;
    content = (
      <div className="flex flex-col gap-4">
        <p className="text-sm text-muted-foreground">
          {detail.ended
            ? "第一次用真錢跑完一期已完成結算，原型階段已結束。以下四項技術豁免當初是為了原型階段暫時放行，現在要逐項重新決定。"
            : "原型階段尚未結束（還沒有任何檔期用真錢結算完成）。"}
        </p>
        <div className="flex flex-col gap-3">
          {detail.exemptions.map((exemption) => (
            <div key={exemption.item} className="rounded-md border border-border p-3">
              <h3 className="text-sm font-semibold text-foreground">{exemption.item}</h3>
              <p className="mt-1 text-sm text-muted-foreground">{exemption.status}</p>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <SidePanel ariaLabel="原型階段結束提醒詳情" onClose={onClose}>
      <div className="flex items-start justify-between gap-3 border-b border-border pb-4">
        <h2 className="font-display text-lg text-foreground">原型階段結束</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="關閉側板"
          className="rounded-md p-2 text-muted-foreground hover:bg-muted"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
      {content}
    </SidePanel>
  );
}
