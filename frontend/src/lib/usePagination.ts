import { useRef, useState } from "react";

/** 清單分頁（互動鐵則⑥，docs/ui-migration-contract.md 第二節）：純前端切片，頁大小預設
 * 12，不打 API、不改資料形狀。`topRef` 掛在清單容器上，翻頁後捲回那裡，不必使用者自己
 * 往上滑（使用者原話：「一路從最上滾動到下沒有耐心看完」）。 */
export function usePagination<T>(items: T[], pageSize = 12) {
  const [page, setPage] = useState(1);
  const topRef = useRef<HTMLDivElement>(null);

  const pageCount = Math.max(1, Math.ceil(items.length / pageSize));
  const safePage = Math.min(page, pageCount);
  const start = (safePage - 1) * pageSize;

  function goToPage(next: number) {
    setPage(next);
    topRef.current?.scrollIntoView({ block: "start", behavior: "smooth" });
  }

  return {
    page: safePage,
    pageCount,
    totalCount: items.length,
    pageItems: items.slice(start, start + pageSize),
    goToPage,
    resetPage: () => setPage(1),
    topRef,
  };
}
