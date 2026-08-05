import type { NavItem } from "@/config/navigation";
import { cn } from "@/lib/utils";

/** 側欄一組導覽項目。active 項目是可點的 <a>（會離開 SPA 導去舊版 Jinja 頁面，
 * 這是刻意的：過渡期舊功能頁本來就是獨立頁面，見票 01 驗收條件）；
 * disabled 項目只顯示原因文字，不做成看起來能點卻沒反應的假連結。 */
export function NavGroup({ items }: { items: NavItem[] }) {
  return (
    <ul className="flex flex-col gap-1">
      {items.map((item) =>
        item.status === "active" ? (
          <li key={item.label}>
            <a
              href={item.href}
              className={cn(
                "block rounded-md px-3 py-2 text-sm font-medium text-secondary",
                "hover:bg-muted hover:text-foreground transition-colors",
              )}
            >
              {item.label}
            </a>
          </li>
        ) : (
          <li key={item.label} title={item.reason} className="px-3 py-2">
            <span className="text-sm font-medium text-muted-foreground/70 cursor-not-allowed">
              {item.label}
            </span>
            {item.reason && (
              <span className="block text-xs text-muted-foreground/60">{item.reason}</span>
            )}
          </li>
        ),
      )}
    </ul>
  );
}
