import { Badge } from "@/components/layout/ui/badge";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { formatRelativeHours } from "@/lib/format";
import type { BriefSummary } from "@/lib/workbenchApi";
import { BUTTON_LABELS, KIND_LABELS, PART_LABELS, SOURCE_LABELS, STATUS_LABELS } from "./copy";

export type BriefPart = keyof typeof PART_LABELS;

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

// 「工單」兩個子清單（全部／已採用）共用的空狀態句——跟「派工任務」的「尚無任務」是兩句不
// 同的話（票面 §1 明講），別合併成一個常數。
const WORK_ORDER_EMPTY = "還沒有工單，從上面的開始生成建立一張。";

function BriefRow({
  brief,
  selected,
  onSelect,
}: {
  brief: BriefSummary;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button type="button" aria-pressed={selected} onClick={onSelect}>
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
  );
}

function SourceGroup({
  label,
  briefs,
  selectedId,
  onSelectBrief,
}: {
  label: string;
  briefs: BriefSummary[];
  selectedId: string | null;
  onSelectBrief: (id: string) => void;
}) {
  return (
    <div className="flex flex-col gap-1">
      <p className="px-3 pt-2 text-xs font-medium text-muted-foreground">{label}</p>
      {briefs.length === 0 ? (
        <p className="px-3 pb-1 text-xs text-muted-foreground">{BUTTON_LABELS.noTasks}</p>
      ) : (
        briefs.map((b) => (
          <BriefRow key={b.id} brief={b} selected={selectedId === b.id} onSelect={() => onSelectBrief(b.id)} />
        ))
      )}
    </div>
  );
}

export function BriefList({
  status,
  briefs,
  errorMessage,
  selectedId,
  onSelectBrief,
  onStartPart,
  activePart,
  onReload,
}: {
  status: "loading" | "error" | "ready";
  briefs: BriefSummary[];
  errorMessage?: string;
  selectedId: string | null;
  onSelectBrief: (id: string) => void;
  onStartPart: (part: BriefPart) => void;
  activePart: BriefPart | null;
  onReload: () => void;
}) {
  const scheduleBriefs = briefs.filter((b) => b.source_kind === "schedule_node");
  const openBriefs = briefs.filter((b) => b.closed_at === null);
  const closedBriefs = briefs.filter((b) => b.closed_at !== null);
  const adoptedBriefs = briefs.filter((b) => Object.values(b.parts).some((p) => p.adopted_round !== null));

  return (
    <nav className="workspace-subnav" aria-label="工作項目">
      <p className="nav-group-label">開始生成</p>
      {(Object.keys(PART_LABELS) as BriefPart[]).map((part) => (
        <button
          key={part}
          type="button"
          aria-pressed={selectedId === null && activePart === part}
          onClick={() => onStartPart(part)}
        >
          {PART_LABELS[part]}
        </button>
      ))}

      <p className="nav-group-label">派工任務</p>
      {status === "loading" && (
        <div className="flex flex-col gap-2 p-2">
          <Skeleton className="h-14" />
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
      {status === "ready" && (
        <>
          <SourceGroup
            label={SOURCE_LABELS.schedule}
            briefs={scheduleBriefs}
            selectedId={selectedId}
            onSelectBrief={onSelectBrief}
          />
          {/* 網站／品牌內容還沒有對應的 source_kind（票面 §1），永遠是空狀態；分組先在
              左欄佔位，等後端有了來源就自然接得上。 */}
          <SourceGroup label={SOURCE_LABELS.website} briefs={[]} selectedId={selectedId} onSelectBrief={onSelectBrief} />
          <SourceGroup
            label={SOURCE_LABELS.brandContent}
            briefs={[]}
            selectedId={selectedId}
            onSelectBrief={onSelectBrief}
          />
        </>
      )}

      <p className="nav-group-label">工單</p>
      {status === "ready" && (
        <>
          <p className="px-3 pt-2 text-xs font-medium text-muted-foreground">全部</p>
          {briefs.length === 0 ? (
            <p className="px-3 pb-1 text-xs text-muted-foreground">{WORK_ORDER_EMPTY}</p>
          ) : (
            <>
              {openBriefs.map((b) => (
                <BriefRow key={b.id} brief={b} selected={selectedId === b.id} onSelect={() => onSelectBrief(b.id)} />
              ))}
              {closedBriefs.length > 0 && (
                <details>
                  <summary className="cursor-pointer px-3 py-2 text-xs text-muted-foreground">已關閉</summary>
                  <div className="flex flex-col gap-1 pl-2">
                    {closedBriefs.map((b) => (
                      <BriefRow
                        key={b.id}
                        brief={b}
                        selected={selectedId === b.id}
                        onSelect={() => onSelectBrief(b.id)}
                      />
                    ))}
                  </div>
                </details>
              )}
            </>
          )}
          <p className="px-3 pt-2 text-xs font-medium text-muted-foreground">已採用</p>
          {adoptedBriefs.length === 0 ? (
            <p className="px-3 pb-1 text-xs text-muted-foreground">{WORK_ORDER_EMPTY}</p>
          ) : (
            adoptedBriefs.map((b) => (
              <BriefRow key={b.id} brief={b} selected={selectedId === b.id} onSelect={() => onSelectBrief(b.id)} />
            ))
          )}
        </>
      )}
    </nav>
  );
}
