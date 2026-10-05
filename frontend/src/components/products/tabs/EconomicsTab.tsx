import { Link } from "react-router-dom";
import { EmptyState } from "@/components/layout/EmptyState";
import type { ProductSellWayBrief } from "@/lib/productsApi";

const amount = (value: number) => Math.round(value).toLocaleString("zh-TW");

/** The products page card's sell-way line (`intake/product/ProductCard` `SellWayRow`, kept in step with it):
 * 「399・打平 249」; a sell-way without a price or a known cost says so instead of printing 0. */
function priceLine(way: ProductSellWayBrief): string {
  return `${way.price === null ? "未定價" : amount(way.price)}・打平 ${way.break_even === null ? "未知" : amount(way.break_even)}`;
}

function OfferChip({ label }: { label: string }) {
  return (
    <span data-slot="chip" data-tone="ok" className="inline-flex shrink-0 items-center rounded-full bg-zone-ok px-1.5 text-[11px] font-medium text-success">
      {label}
    </span>
  );
}

/** Product onboarding step 4 賣法與價格, where a knowledge product's money is edited. */
const sellWaysStepPath = (brandId: string, productId: string) =>
  `/brands/${encodeURIComponent(brandId)}/products/${encodeURIComponent(productId)}/onboarding?step=4`;

/** 產品經濟數字分頁 (F50-I15, Contract R; drill-11 R6 A3): a knowledge product carries no money — its price and cost
 * live on its sell-ways, which planners read. The tab lists the served `sell_ways` (name, offers, price・break-even —
 * the products page card's line) and links to onboarding step 4, where they are edited. */
export function EconomicsTab({ brandId, productId, sellWays }: {
  brandId: string;
  productId: string;
  sellWays: ProductSellWayBrief[];
}) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="font-display text-lg text-foreground">產品經濟數字</h2>
        <Link
          to={sellWaysStepPath(brandId, productId)}
          className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90"
        >
          到建檔第 4 步改 →
        </Link>
      </div>

      {sellWays.length === 0 ? (
        <EmptyState title="還沒有賣法" description="售價與成本記在賣法上；建好賣法，之後才算得出這個產品的 CPA 與 ROAS 標準。" />
      ) : (
        <div data-slot="sell-ways" className="flex flex-col gap-2 rounded-md border border-border bg-card p-4 text-sm shadow-[var(--shadow-card)]">
          {sellWays.map((way) => (
            <div key={way.id} data-slot="sell-way-row" className="flex justify-between gap-2">
              <span className="flex min-w-0 flex-wrap items-center gap-1">
                <span className="[overflow-wrap:anywhere]">{way.name}</span>
                {way.offer_labels.map((offer) => <OfferChip key={offer} label={offer} />)}
              </span>
              <span className="shrink-0 whitespace-nowrap tabular-nums">{priceLine(way)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
