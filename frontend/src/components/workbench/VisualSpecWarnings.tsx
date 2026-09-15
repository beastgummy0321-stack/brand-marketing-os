import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getVisualSpec, type VisualSpecWarning } from "@/lib/workbenchApi";

/** 品牌事實分頁頂端的視覺基礎提醒（F07-I12，F07 Decision 24／`ARCHITECTURE.md` §5.9）：字串跟
 * 連結都是 `GET .../visual-spec` 給的，這支不重打規則；抓不到（沒有警告或 fetch 失敗）就整個
 * 不顯示，不當作錯誤處理。`FactsTab.tsx`（`components/library/`）透過 `index.ts` 匯入。 */
export function VisualSpecWarnings({ brandId }: { brandId: string }) {
  const [warnings, setWarnings] = useState<VisualSpecWarning[]>([]);

  useEffect(() => {
    let alive = true;
    setWarnings([]);
    getVisualSpec(brandId)
      .then((res) => {
        if (alive) setWarnings(res.warnings);
      })
      .catch(() => {
        if (alive) setWarnings([]);
      });
    return () => {
      alive = false;
    };
  }, [brandId]);

  if (warnings.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      {warnings.map((warning) => (
        <div
          key={warning.href + warning.text}
          className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-warning/40 bg-warning/5 p-3 text-sm text-foreground"
        >
          <span>{warning.text}</span>
          <Link to={warning.href} className="shrink-0 font-medium text-primary hover:underline">
            去品牌智庫
          </Link>
        </div>
      ))}
    </div>
  );
}
