import type { DashboardBrandCard } from "@/lib/api";
import { formatCurrency, formatMomPct } from "@/lib/format";
import { cn } from "@/lib/utils";

/** 品牌卡片（票 02-overview-cards）：健康度燈號＋本月營收環比＋檔期狀態＋下一步留位。
 * 點卡片進單品牌駕駛艙（票 03）——`?brand=` 查詢字串而不是路徑片段，直接落在 SPA
 * 掛載根目錄 `/app/`，重新整理／直接貼網址都吃得到（StaticFiles html=True 只認
 * 掛載根目錄的 index.html，子路徑沒有 catch-all 會 404，見票 03 實作筆記）。 */

const HEALTH_LABEL: Record<DashboardBrandCard["health"], string> = {
  red: "需要關注",
  yellow: "有警示待處理",
  green: "一切正常",
};

const HEALTH_DOT_CLASS: Record<DashboardBrandCard["health"], string> = {
  red: "bg-danger",
  yellow: "bg-warning",
  green: "bg-success",
};

export function BrandCard({ card }: { card: DashboardBrandCard }) {
  return (
    <a
      href={`/app/?brand=${encodeURIComponent(card.brand_id)}`}
      className="flex flex-col gap-3 rounded-lg border border-border bg-card p-5 shadow-[var(--shadow-card)] transition-shadow hover:shadow-md"
    >
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-display text-lg text-foreground">{card.brand_name}</h2>
        <span className="flex shrink-0 items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <span
            className={cn("h-2.5 w-2.5 rounded-full", HEALTH_DOT_CLASS[card.health])}
            aria-hidden="true"
          />
          {HEALTH_LABEL[card.health]}
        </span>
      </div>

      <div>
        <p className="text-2xl font-semibold text-foreground">
          {formatCurrency(card.revenue_this_month)}
        </p>
        <p className="text-sm text-muted-foreground">
          本月營收 {formatMomPct(card.revenue_mom_pct)}
        </p>
      </div>

      <p className="text-sm text-secondary">
        檔期：{card.active_cycle ? card.active_cycle.status_label : "尚無進行中檔期"}
      </p>

      <p className="text-sm text-muted-foreground">
        {card.next_step ?? "下一步指南卡即將推出"}
      </p>
    </a>
  );
}
