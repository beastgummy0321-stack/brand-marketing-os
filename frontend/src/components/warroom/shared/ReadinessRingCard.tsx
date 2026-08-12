import { ProgressRing } from "@/components/layout/ProgressRing";
import type { ReadinessRing } from "@/lib/warroomApi";
import { Badge } from "./Badge";

/** S8R.13-15：交接總分環——大環形進度（N/M 通過）＋展開明細，未過項排最上，每項附「去處理」
 * 按鈕，畫面內捲動到對應子區塊（`fix_anchor` 是前端錨點 id 不是 URL，不換頁，鐵則②精神延伸，
 * S8R.15）。 */
export function ReadinessRingCard({ ring }: { ring: ReadinessRing }) {
  const pct = ring.total === 0 ? 100 : Math.round((ring.passed / ring.total) * 100);
  const allPassed = ring.passed === ring.total;

  function goFix(anchor: string) {
    document.getElementById(anchor)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-border bg-card p-4 shadow-[var(--shadow-card)] sm:flex-row sm:items-center">
      <ProgressRing value={pct} colorClassName={allPassed ? "stroke-success" : "stroke-primary"} className="shrink-0">
        <span className="font-display text-xl text-foreground">
          {ring.passed}／{ring.total}
        </span>
        <span className="text-xs text-muted-foreground">通過</span>
      </ProgressRing>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-foreground">{allPassed ? "交接前置作業都確認過了" : `還有 ${ring.total - ring.passed} 項沒確認`}</p>
        <ul className="mt-2 flex flex-col gap-1.5">
          {ring.items.map((item) => (
            <li key={item.key} className="flex items-center justify-between gap-2 text-sm">
              <span className="flex items-center gap-1.5 text-foreground">
                <Badge tone={item.passed ? "success" : "danger"}>{item.passed ? "通過" : "未過"}</Badge>
                {item.label}
              </span>
              {!item.passed && (
                <button type="button" onClick={() => goFix(item.fix_anchor)} className="shrink-0 text-xs font-medium text-primary hover:underline">
                  去處理
                </button>
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
