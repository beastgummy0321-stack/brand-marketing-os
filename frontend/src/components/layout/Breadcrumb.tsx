export interface BreadcrumbItem {
  label: string;
  /** 有 href 才是可點的上層；當前頁不給 href。 */
  href?: string;
}

/** 頁面麵包屑（票 09-empty-states-tour，規格使用者故事 24）：讓任何深度、任何載入狀態
 * 的頁面都看得到自己在哪、一鍵回上層，不必只靠側欄。呼叫端要在讀取中／讀取失敗／
 * 有資料三種狀態都放同一份麵包屑（見 Overview、CockpitPage）。 */
export function Breadcrumb({ items }: { items: BreadcrumbItem[] }) {
  return (
    <nav aria-label="麵包屑" className="flex items-center gap-1.5 text-sm text-muted-foreground">
      {items.map((item, index) => (
        <span key={item.label} className="flex items-center gap-1.5">
          {index > 0 && <span aria-hidden="true">/</span>}
          {item.href ? (
            <a href={item.href} className="text-primary underline-offset-4 hover:underline">
              {item.label}
            </a>
          ) : (
            <span aria-current="page" className="text-foreground">
              {item.label}
            </span>
          )}
        </span>
      ))}
    </nav>
  );
}
