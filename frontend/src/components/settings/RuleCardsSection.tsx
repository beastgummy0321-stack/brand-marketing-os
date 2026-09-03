import { useEffect, useState } from "react";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import type { BrandOption, RuleCard } from "@/lib/settingsApi";
import { fetchBrandOptions, fetchRuleCards, resetRuleCard, saveRuleCard } from "@/lib/settingsApi";
import { SectionCard } from "./shared/SectionCard";
import { SaveButton } from "./shared/SaveButton";
import { useFormSubmit } from "@/lib/useFormSubmit";

type BrandsState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; brands: BrandOption[] };

type CardsState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; cards: RuleCard[] };

/** 品牌規則卡參數區塊（S15.29–S15.33）：品牌選擇器＋規則卡，新設計（見契約「拿不準
 * 的點」1，暫定留在 S15），選了品牌才讀該品牌的卡。 */
export function RuleCardsSection() {
  const [brandsState, setBrandsState] = useState<BrandsState>({ status: "loading" });
  const [brandId, setBrandId] = useState("");
  const [cardsState, setCardsState] = useState<CardsState>({ status: "idle" });

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

  function loadCards(id: string) {
    setCardsState({ status: "loading" });
    fetchRuleCards(id)
      .then((data) => setCardsState({ status: "ready", cards: data.cards }))
      .catch((err: unknown) =>
        setCardsState({
          status: "error",
          message: err instanceof Error ? err.message : "規則卡讀取失敗，請稍後再試。",
        }),
      );
  }

  useEffect(() => {
    if (brandId) loadCards(brandId);
    else setCardsState({ status: "idle" });
  }, [brandId]);

  function handleCardUpdated(updated: RuleCard) {
    setCardsState((prev) =>
      prev.status !== "ready"
        ? prev
        : { status: "ready", cards: prev.cards.map((c) => (c.key === updated.key ? updated : c)) },
    );
  }

  return (
    <SectionCard title="品牌規則卡參數">
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
          description="要先建立品牌，才能設定它的廣告護欄門檻。"
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

          {cardsState.status === "loading" && (
            <div className="grid grid-cols-[repeat(auto-fit,minmax(420px,500px))] gap-4">
              {Array.from({ length: 6 }, (_, i) => (
                <Skeleton key={i} className="h-48" />
              ))}
            </div>
          )}
          {cardsState.status === "error" && (
            <EmptyState
              title="規則卡讀取失敗"
              description={cardsState.message}
              onAction={() => loadCards(brandId)}
              actionLabel="重新載入"
            />
          )}
          {cardsState.status === "ready" && (
            <div className="grid grid-cols-[repeat(auto-fit,minmax(420px,500px))] gap-4">
              {cardsState.cards.map((card) => (
                <RuleCardItem key={card.key} brandId={brandId} card={card} onUpdated={handleCardUpdated} />
              ))}
            </div>
          )}
        </>
      )}
    </SectionCard>
  );
}

function RuleCardItem({
  brandId,
  card,
  onUpdated,
}: {
  brandId: string;
  card: RuleCard;
  onUpdated: (updated: RuleCard) => void;
}) {
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(card.fields.map((f) => [f.key, String(f.value)])),
  );

  const saveForm = useFormSubmit(async () => {
    const parsed: Record<string, number> = {};
    for (const [key, raw] of Object.entries(values)) parsed[key] = Number(raw);
    const updated = await saveRuleCard(brandId, card.key, parsed);
    onUpdated(updated);
  });

  const resetForm = useFormSubmit(async () => {
    const updated = await resetRuleCard(brandId, card.key);
    setValues(Object.fromEntries(updated.fields.map((f) => [f.key, String(f.value)])));
    onUpdated(updated);
  });

  function handleReset() {
    if (window.confirm(`確定要把「${card.title}」的所有欄位重設回系統預設值？`)) {
      void resetForm.submit();
    }
  }

  return (
    <div className="flex flex-col gap-3 rounded-md border border-border p-4">
      <div>
        <h3 className="text-sm font-semibold text-foreground">{card.title}</h3>
        <p className="mt-1 text-xs text-muted-foreground">{card.description}</p>
      </div>
      <form
        className="flex flex-col gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          void saveForm.submit();
        }}
      >
        {card.fields.map((f) => (
          <label key={f.key} className="flex flex-col gap-1 text-xs">
            <span className="flex items-center gap-1.5 font-medium text-foreground">
              {f.label}
              {f.customized && (
                <span className="rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                  已自訂
                </span>
              )}
            </span>
            <div className="flex items-center gap-2">
              <input
                type="number"
                step="any"
                value={values[f.key]}
                onChange={(e) => setValues((prev) => ({ ...prev, [f.key]: e.target.value }))}
                className="w-full rounded-md border border-border px-2 py-1.5 text-sm text-foreground"
              />
              <span className="shrink-0 text-muted-foreground">{f.unit}</span>
            </div>
            <span className="text-muted-foreground">{f.help}</span>
          </label>
        ))}
        {saveForm.error && <p className="text-xs text-danger">{saveForm.error}</p>}
        {resetForm.error && <p className="text-xs text-danger">{resetForm.error}</p>}
        <div className="flex items-center gap-2">
          <SaveButton saving={saveForm.saving} label="儲存這張卡" />
          <button
            type="button"
            onClick={handleReset}
            disabled={resetForm.saving}
            className="rounded-md border border-border px-3 py-2 text-xs font-medium text-muted-foreground hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
          >
            {resetForm.saving ? "處理中…" : "重設為系統預設值"}
          </button>
        </div>
      </form>
    </div>
  );
}
