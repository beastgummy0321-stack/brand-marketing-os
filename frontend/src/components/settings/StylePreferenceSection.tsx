import { useEffect, useState } from "react";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { fetchBrandOptions, fetchStylePreference, saveStylePreference, type BrandOption } from "@/lib/settingsApi";
import { useFormSubmit } from "@/lib/useFormSubmit";
import { SaveButton } from "./shared/SaveButton";
import { SectionCard } from "./shared/SectionCard";

type BrandState = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; brands: BrandOption[] };

/** 圖片風格偏好（F2 畫面 4）：品牌選擇模式與規則卡相同，文字由後端品牌設定保存。 */
export function StylePreferenceSection() {
  const [brands, setBrands] = useState<BrandState>({ status: "loading" });
  const [brandId, setBrandId] = useState("");
  const [text, setText] = useState("");
  const [loadingText, setLoadingText] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  function loadBrands() {
    setBrands({ status: "loading" });
    fetchBrandOptions().then((items) => setBrands({ status: "ready", brands: items })).catch((error: unknown) => setBrands({ status: "error", message: error instanceof Error ? error.message : "品牌清單讀取失敗，請稍後再試。" }));
  }

  useEffect(loadBrands, []);
  useEffect(() => {
    if (!brandId) return;
    setLoadingText(true);
    setLoadError(null);
    fetchStylePreference(brandId).then((data) => setText(data.text)).catch((error: unknown) => setLoadError(error instanceof Error ? error.message : "風格偏好讀取失敗，請稍後再試。")).finally(() => setLoadingText(false));
  }, [brandId]);

  const form = useFormSubmit(async () => {
    const saved = await saveStylePreference(brandId, text);
    setText(saved.text);
  });

  return (
    <SectionCard title="圖片風格偏好">
      {brands.status === "loading" && <Skeleton className="h-9 w-64" />}
      {brands.status === "error" && <EmptyState title="品牌清單讀取失敗" description={brands.message} onAction={loadBrands} actionLabel="重新載入" />}
      {brands.status === "ready" && brands.brands.length === 0 && <EmptyState title="還沒有任何品牌" description="要先建立品牌，才能寫下圖片風格偏好。" actionHref="/" actionInternal actionLabel="先去建一個品牌" />}
      {brands.status === "ready" && brands.brands.length > 0 && (
        <>
          <label className="flex max-w-sm flex-col gap-1 text-sm"><span className="font-medium text-foreground">選擇品牌</span><select value={brandId} onChange={(event) => setBrandId(event.target.value)} className="rounded-md border border-border px-3 py-2 text-foreground"><option value="">請選擇品牌</option>{brands.brands.map((brand) => <option key={brand.brand_id} value={brand.brand_id}>{brand.brand_name}</option>)}</select></label>
          {loadingText && <Skeleton className="h-28 w-full" />}
          {loadError && <p className="text-sm text-danger">{loadError}</p>}
          {brandId && !loadingText && !loadError && <form className="flex flex-col gap-3" onSubmit={(event) => { event.preventDefault(); void form.submit(); }}><textarea value={text} onChange={(event) => setText(event.target.value)} rows={4} className="rounded-md border border-border px-3 py-2 text-sm text-foreground" /><p className="text-sm text-muted-foreground">單次生成時可臨時換風格，不會動到這裡</p>{form.error && <p className="text-sm text-danger">{form.error}</p>}<div><SaveButton saving={form.saving} label="儲存" /></div></form>}
        </>
      )}
    </SectionCard>
  );
}
