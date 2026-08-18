import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import type { BrandOption } from "@/lib/settingsApi";
import { fetchBrandOptions } from "@/lib/settingsApi";
import { PRESS_FEEDBACK, cn } from "@/lib/utils";
import { SectionCard } from "./shared/SectionCard";

type BrandsState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; brands: BrandOption[] };

/** 追蹤健檢入口（票 T0）：品牌層工具，設定頁只放「選品牌＋前往」，跟
 * `AutonomySection`／`RuleCardsSection` 同一套品牌選擇器慣例，不重寫第二份。 */
export function TrackingHealthEntrySection() {
  const [brandsState, setBrandsState] = useState<BrandsState>({ status: "loading" });
  const [brandId, setBrandId] = useState("");

  function loadBrands() {
    setBrandsState({ status: "loading" });
    fetchBrandOptions()
      .then((brands) => setBrandsState({ status: "ready", brands }))
      .catch((err: unknown) =>
        setBrandsState({
          status: "error",
          message: err instanceof Error ? err.message : "品牌清單讀取失敗，請稍後再試。",
        }),
      );
  }

  useEffect(loadBrands, []);

  return (
    <SectionCard title="追蹤健檢" description="廣告錢花下去前，先確認每個品牌的訂單追得回來。">
      {brandsState.status === "loading" && <Skeleton className="h-9 w-64" />}
      {brandsState.status === "error" && (
        <EmptyState title="品牌清單讀取失敗" description={brandsState.message} onAction={loadBrands} actionLabel="重新載入" />
      )}
      {brandsState.status === "ready" && brandsState.brands.length === 0 && (
        <EmptyState title="還沒有任何品牌" description="要先建立品牌，才能檢查它的追蹤設定。" actionHref="/" actionInternal actionLabel="先去建一個品牌" />
      )}
      {brandsState.status === "ready" && brandsState.brands.length > 0 && (
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-foreground">選擇品牌</span>
            <select
              value={brandId}
              onChange={(event) => setBrandId(event.target.value)}
              className="w-full max-w-sm rounded-md border border-border px-3 py-2 text-sm text-foreground"
            >
              <option value="">請選擇品牌</option>
              {brandsState.brands.map((brand) => (
                <option key={brand.brand_id} value={brand.brand_id}>
                  {brand.brand_name}
                </option>
              ))}
            </select>
          </label>
          {brandId ? (
            <Link
              to={`/brands/${encodeURIComponent(brandId)}/tracking`}
              className={cn("rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90", PRESS_FEEDBACK)}
            >
              前往追蹤健檢
            </Link>
          ) : (
            <span className="rounded-md border border-border px-3 py-1.5 text-sm text-muted-foreground opacity-50">前往追蹤健檢</span>
          )}
        </div>
      )}
    </SectionCard>
  );
}
