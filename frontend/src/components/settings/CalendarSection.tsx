import { useEffect, useState } from "react";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import type { BrandOption, CalendarCategory } from "@/lib/settingsApi";
import { fetchBrandOptions, fetchCalendarCategories, toggleCalendarCategory } from "@/lib/settingsApi";
import { SectionCard } from "./shared/SectionCard";

type BrandsState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; brands: BrandOption[] };

type CategoriesState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; categories: CalendarCategory[] };

/** 節日提醒永久關閉開關（原舊頁 `/brands/{id}/settings/ads` 節日提醒小節）：品牌選擇模式
 * 同 RuleCardsSection，選了品牌才讀該品牌逐節日類別的現況。關掉＝以後系統業種比對判成
 * 相關也不再提醒這個節日；重新打開＝恢復正常提醒。 */
export function CalendarSection() {
  const [brandsState, setBrandsState] = useState<BrandsState>({ status: "loading" });
  const [brandId, setBrandId] = useState("");
  const [categoriesState, setCategoriesState] = useState<CategoriesState>({ status: "idle" });
  const [pending, setPending] = useState<string | null>(null);
  const [toggleError, setToggleError] = useState<string | null>(null);

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

  function loadCategories(id: string) {
    setCategoriesState({ status: "loading" });
    fetchCalendarCategories(id)
      .then((data) => setCategoriesState({ status: "ready", categories: data.categories }))
      .catch((err: unknown) =>
        setCategoriesState({
          status: "error",
          message: err instanceof Error ? err.message : "節日提醒清單讀取失敗，請稍後再試。",
        }),
      );
  }

  useEffect(() => {
    if (brandId) loadCategories(brandId);
    else setCategoriesState({ status: "idle" });
  }, [brandId]);

  async function handleToggle(category: string, enabled: boolean) {
    setPending(category);
    setToggleError(null);
    try {
      const updated = await toggleCalendarCategory(brandId, category, enabled);
      setCategoriesState((prev) =>
        prev.status !== "ready"
          ? prev
          : { status: "ready", categories: prev.categories.map((c) => (c.category === updated.category ? updated : c)) },
      );
    } catch (err) {
      setToggleError(err instanceof Error ? err.message : "更新失敗，請稍後再試。");
    } finally {
      setPending(null);
    }
  }

  return (
    <SectionCard title="節日提醒">
      <p className="text-sm text-muted-foreground">
        系統會依品牌業種提醒相關節日檔期（農曆新年、母親節等）。關掉某個節日＝以後系統判成相關也不會再提醒，
        直到你在這裡重新打開；不影響其他節日的提醒。
      </p>
      {brandsState.status === "loading" && <Skeleton className="h-9 w-64" />}
      {brandsState.status === "error" && (
        <EmptyState
          title="品牌清單讀取失敗"
          description={brandsState.message}
          onAction={loadBrands}
          actionLabel="重新載入"
        />
      )}
      {brandsState.status === "ready" && brandsState.brands.length === 0 && (
        <EmptyState
          title="還沒有任何品牌"
          description="要先建立品牌，才能設定它的節日提醒。"
          actionHref="/"
          actionInternal
          actionLabel="先去建一個品牌"
        />
      )}
      {brandsState.status === "ready" && brandsState.brands.length > 0 && (
        <>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-foreground">選擇品牌</span>
            <select
              value={brandId}
              onChange={(e) => setBrandId(e.target.value)}
              className="w-full max-w-sm rounded-md border border-border px-3 py-2 text-sm text-foreground"
            >
              <option value="">請選擇品牌</option>
              {brandsState.brands.map((b) => (
                <option key={b.brand_id} value={b.brand_id}>
                  {b.brand_name}
                </option>
              ))}
            </select>
          </label>

          {categoriesState.status === "loading" && (
            <div className="flex flex-col gap-2">
              {Array.from({ length: 4 }, (_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          )}
          {categoriesState.status === "error" && (
            <EmptyState
              title="節日提醒清單讀取失敗"
              description={categoriesState.message}
              onAction={() => loadCategories(brandId)}
              actionLabel="重新載入"
            />
          )}
          {categoriesState.status === "ready" && (
            <>
              {toggleError && <p className="text-sm text-danger">{toggleError}</p>}
              <ul className="flex flex-col gap-2">
                {categoriesState.categories.map((cat) => (
                  <li
                    key={cat.category}
                    className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2"
                  >
                    <span className="text-sm text-foreground">{cat.label}</span>
                    <label className="flex items-center gap-2 text-xs text-muted-foreground">
                      {pending === cat.category ? "處理中…" : cat.enabled ? "提醒中" : "已永久關閉"}
                      <input
                        type="checkbox"
                        checked={cat.enabled}
                        disabled={pending === cat.category}
                        onChange={(e) => void handleToggle(cat.category, e.target.checked)}
                      />
                    </label>
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </SectionCard>
  );
}
