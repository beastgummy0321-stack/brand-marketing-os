import { Badge } from "@/components/layout/ui/badge";
import { EmptyState } from "@/components/layout/EmptyState";
import { PageTabs } from "@/components/layout/PageTabs";
import { Skeleton } from "@/components/layout/Skeleton";
import { formatRelativeHours } from "@/lib/format";
import type { BriefSummary, WorkbenchBriefStatus } from "@/lib/workbenchApi";
import { KIND_LABELS, STATUS_LABELS } from "./copy";

const FILTER_ITEMS: { value: WorkbenchBriefStatus; label: string }[] = [
  { value: "active", label: "進行中" },
  { value: "closed", label: "已關閉" },
  { value: "all", label: "全部" },
];

/** 每一列的一行摘要：排程節點用節點名稱；否則用產品名稱；都沒有就退回種類標籤。
 *
 * 票面原文還要「或 `request.free_text` 的前 30 字」——`GET /briefs` 回的是 `BriefSummary`
 * （`workbenchApi.ts`，票 03），這個型別沒有 `request` 欄位；`app/workbench/repository.py`
 * 的 `_brief_summary()`（清單／list_briefs 用的那個 shaper，:317-329）也真的沒有寫
 * `detail["request"]` 這一行——只有單筆 `brief_detail()`（:357）才加。清單 API 本來就沒有
 * 這個欄位可讀，不是這裡漏接；`blocked-upstream`（票面「Not touched」段本來就講明這種缺口
 * 怎麼處理），不在這裡另外打一次 `fetchBrief` 去湊——那是把清單摘要變成 N+1 支 detail
 * 請求，比缺一行摘要文字更貴。 */
function summaryLine(brief: BriefSummary): string {
  if (brief.source_kind === "schedule_node") {
    const nodeName = brief.source_ref?.node_name;
    if (typeof nodeName === "string" && nodeName) return nodeName;
  }
  return brief.product_name ?? KIND_LABELS[brief.kind] ?? brief.kind;
}

/** 匯出給 `BriefDetail.tsx` 同資料夾內重用（`BriefDetail` 型別的欄位是 `BriefSummary` 的
 * 超集，同一顆判斷式對兩邊都成立）——同功能資料夾內互相 import 不受 dependency-cruiser
 * 限制（ADR 0060 只管跨功能）。 */
export function StatusBadge({ brief }: { brief: BriefSummary }) {
  if (brief.closed_at !== null) return <Badge variant="secondary">{STATUS_LABELS.closed}</Badge>;
  if (brief.status === "queued" || brief.status === "running") return <Badge>{STATUS_LABELS.processing}</Badge>;
  if (brief.status === "failed") return <Badge variant="destructive">{STATUS_LABELS.failed}</Badge>;
  // status='done' 但沒有任何 part 產出過（沒有 part 要跑，票 04 amendment 第 2 點）：
  // 這是閒置，不是完成——用 `parts`（`_part_summaries()` 只對有輸出列的 part 建 key）
  // 判斷「零產出」，跟 BriefDetail 的 `outputs.length === 0` 是同一件事的兩種讀法。
  if (brief.status === "done" && Object.keys(brief.parts).length === 0) {
    return <Badge variant="secondary">{STATUS_LABELS.idle}</Badge>;
  }
  return <Badge>{STATUS_LABELS.done}</Badge>;
}

function emptyDescription(filter: WorkbenchBriefStatus): string {
  if (filter === "active") return "還沒有進行中的工單；按右上角新工單建立一張。";
  if (filter === "closed") return "還沒有已關閉的工單。";
  return "這個品牌還沒有任何工單；按右上角新工單建立一張。";
}

export function BriefList({
  status,
  briefs,
  errorMessage,
  filter,
  onFilterChange,
  selectedId,
  onSelect,
  onReload,
}: {
  status: "loading" | "error" | "ready";
  briefs: BriefSummary[];
  errorMessage?: string;
  filter: WorkbenchBriefStatus;
  onFilterChange: (status: WorkbenchBriefStatus) => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onReload: () => void;
}) {
  return (
    <nav className="workspace-subnav" aria-label="工單清單">
      <PageTabs label="工單篩選" items={FILTER_ITEMS} value={filter} onChange={onFilterChange} />
      {status === "loading" && (
        <div className="flex flex-col gap-2 p-2">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-14" />
          ))}
        </div>
      )}
      {status === "error" && (
        <div className="p-2">
          <EmptyState
            title="讀取失敗"
            description={errorMessage ?? "請稍後再試。"}
            onAction={onReload}
            actionLabel="重新載入"
          />
        </div>
      )}
      {status === "ready" && briefs.length === 0 && (
        <div className="p-2">
          <EmptyState title="沒有工單" description={emptyDescription(filter)} />
        </div>
      )}
      {status === "ready" &&
        briefs.map((brief) => (
          <button
            key={brief.id}
            type="button"
            aria-pressed={selectedId === brief.id}
            onClick={() => onSelect(brief.id)}
          >
            <span className="flex w-full flex-col items-start gap-1 text-left">
              <span className="text-xs font-medium text-muted-foreground">
                {KIND_LABELS[brief.kind] ?? brief.kind}
              </span>
              <span className="line-clamp-1 text-sm">{summaryLine(brief)}</span>
              <span className="flex items-center gap-2">
                <StatusBadge brief={brief} />
                <span className="text-xs text-muted-foreground">
                  {formatRelativeHours(brief.created_at)}
                </span>
              </span>
            </span>
          </button>
        ))}
    </nav>
  );
}
