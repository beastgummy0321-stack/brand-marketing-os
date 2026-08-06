import { Link } from "react-router-dom";
import type { NavItem } from "@/config/navigation";
import { cn } from "@/lib/utils";

const LINK_CLASS = cn(
  "block rounded-md px-3 py-2 text-sm font-medium text-secondary",
  "hover:bg-muted hover:text-foreground transition-colors",
);

/** 側欄一組導覽項目。active 項目多半是離開 SPA 的 <a>（去舊版 Jinja 頁面，這是刻意的：
 * 過渡期舊功能頁本來就是獨立頁面，見票 01 驗收條件），`internal` 項目（票 05-spa-routing）
 * 是 SPA 內部路徑，改用 react-router 的 `Link`；disabled 項目只顯示原因文字，
 * 不做成看起來能點卻沒反應的假連結。 */
export function NavGroup({ items }: { items: NavItem[] }) {
  return (
    <ul className="flex flex-col gap-1">
      {items.map((item) =>
        item.status === "active" ? (
          <li key={item.label}>
            {item.internal ? (
              <Link to={item.href!} className={LINK_CLASS}>
                {item.label}
              </Link>
            ) : (
              <a href={item.href} className={LINK_CLASS}>
                {item.label}
              </a>
            )}
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
