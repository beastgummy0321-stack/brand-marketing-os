import { Link } from "react-router-dom";
import type { DashboardBrandCard } from "@/lib/api";
import { formatCurrency, formatMomPct } from "@/lib/format";
import { ArrowUpRight } from "lucide-react";
import { internalHref } from "@/lib/internalHref";
import { cn } from "@/lib/utils";

/** 品牌卡片（票 02-overview-cards）：健康度燈號＋本月營收環比＋檔期狀態＋
 * 最重要一件下一步（票 04-guide-card-engine 接上指南卡引擎真貨源）。
 * 點卡片進單品牌駕駛艙（票 03）——路徑式網址 `/brands/:brandId`（票 05-spa-routing），
 * 用 react-router 的 `Link` 導航；重新整理／直接貼網址都吃得到（後端 `/app` catch-all
 * 見 app/main.py）。
 *
 * next_step 連的網址（舊功能頁）是 SPA 之外的 Jinja 頁面，跟卡片本身（進新殼駕駛艙）
 * 不是同一個導覽系統，兩個連結也不能用巢狀 `<a>`／`<Link>`（無效 HTML）；next_step
 * 維持 onClick + stopPropagation 用 window.location 做整頁跳轉。 */

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
    <article className="surface flex flex-col gap-5 p-6 transition-colors hover:border-primary/40">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-lg"><Link className="hover:text-primary" to={`/brands/${encodeURIComponent(card.brand_id)}`}>{card.brand_name}</Link></h2>
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

      {card.next_step ? (
        <Link to={internalHref(card.next_step.action_url)} className="border-t border-border pt-4 text-sm text-primary hover:underline">
          {card.next_step.title} →
        </Link>
      ) : (
        <p className="text-sm text-muted-foreground">一切正常</p>
      )}
      <Link className="flex items-center justify-between text-xs text-muted-foreground hover:text-primary" to={`/brands/${encodeURIComponent(card.brand_id)}`}>進入品牌工作區<ArrowUpRight size={15}/></Link>
    </article>
  );
}
