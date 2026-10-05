import { ChevronLeft, ChevronRight } from "lucide-react";

/** 全站共用分頁列（互動鐵則⑥）：左右箭頭＋「第 N / M 頁」＋總筆數。只有一頁時不顯示。
 * 純受控元件，切片邏輯在 `lib/usePagination.ts`，這裡只負責畫面與觸發翻頁。 */
export function Pager({
  page,
  pageCount,
  totalCount,
  onChange,
}: {
  page: number;
  pageCount: number;
  totalCount: number;
  onChange: (page: number) => void;
}) {
  if (pageCount <= 1) return null;

  return (
    <div className="flex items-center justify-between border-t border-border pt-3 text-sm text-muted-foreground">
      <span>共 {totalCount} 筆</span>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => onChange(page - 1)}
          disabled={page <= 1} // DISABLED_OK: structural — there is no page before the first
          aria-label="上一頁"
          className="rounded-md border border-border p-1.5 text-foreground hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-40"
        >
          <ChevronLeft className="h-4 w-4" aria-hidden="true" />
        </button>
        <span className="tabular-nums">
          第 {page} / {pageCount} 頁
        </span>
        <button
          type="button"
          onClick={() => onChange(page + 1)}
          disabled={page >= pageCount} // DISABLED_OK: structural — there is no page after the last
          aria-label="下一頁"
          className="rounded-md border border-border p-1.5 text-foreground hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-40"
        >
          <ChevronRight className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
