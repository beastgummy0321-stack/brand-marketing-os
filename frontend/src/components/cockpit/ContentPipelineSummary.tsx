import type { ContentPipeline } from "@/lib/api";

/** 內容產線小計（票 05-alerts-fuel-pipeline）：待審（DRAFT，還沒過素材採用關卡）／
 * 已發（APPROVED，已採用）則數。含零筆空狀態——兩者皆 0 就直接顯示 0，不隱藏區塊。 */
export function ContentPipelineSummary({ pipeline }: { pipeline: ContentPipeline }) {
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-card p-5 shadow-[var(--shadow-card)]">
      <p className="text-sm text-muted-foreground">內容產線</p>
      <div className="flex items-center gap-6">
        <div>
          <p className="text-lg font-semibold text-foreground">{pipeline.pending}</p>
          <p className="text-xs text-muted-foreground">待審</p>
        </div>
        <div>
          <p className="text-lg font-semibold text-foreground">{pipeline.published}</p>
          <p className="text-xs text-muted-foreground">已發</p>
        </div>
      </div>
    </div>
  );
}
