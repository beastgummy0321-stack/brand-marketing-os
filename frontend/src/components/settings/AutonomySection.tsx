import { useEffect, useState } from "react";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import type { AutonomyMode, BrandOption, RuleCard } from "@/lib/settingsApi";
import { fetchBrandOptions, fetchRuleCards, saveRuleCard } from "@/lib/settingsApi";
import { useFormSubmit } from "@/lib/useFormSubmit";
import { SectionCard } from "./shared/SectionCard";

type BrandsState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; brands: BrandOption[] };

type CardState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; card: RuleCard };

const MODES: { value: AutonomyMode; label: string; description: string }[] = [
  {
    value: 1,
    label: "保守檔",
    description: "提案與上線都等你核可，再照清單手動執行。",
  },
  {
    value: 2,
    label: "放手檔",
    description: "平台寫入 API 開通後，煞車內的小幅調整可自動執行。",
  },
];

function cardMode(card: RuleCard): AutonomyMode {
  const value = card.fields.find((field) => field.key === "mode")?.value;
  return value === 2 ? 2 : 1;
}

/** 品牌層投放自動度：兩個固定選項直接寫入既有 autonomy 規則卡。 */
export function AutonomySection() {
  const [brandsState, setBrandsState] = useState<BrandsState>({ status: "loading" });
  const [brandId, setBrandId] = useState("");
  const [cardState, setCardState] = useState<CardState>({ status: "idle" });

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

  function loadCard(id: string) {
    setCardState({ status: "loading" });
    fetchRuleCards(id)
      .then((data) => {
        const card = data.cards.find((item) => item.key === "autonomy");
        if (!card) throw new Error("找不到投放自動度設定，請重新載入。");
        setCardState({ status: "ready", card });
      })
      .catch((err: unknown) =>
        setCardState({
          status: "error",
          message: err instanceof Error ? err.message : "投放自動度讀取失敗，請稍後再試。",
        }),
      );
  }

  useEffect(() => {
    if (brandId) loadCard(brandId);
    else setCardState({ status: "idle" });
  }, [brandId]);

  const saveForm = useFormSubmit(async (mode: AutonomyMode) => {
    const card = await saveRuleCard(brandId, "autonomy", { mode });
    setCardState({ status: "ready", card });
  });

  return (
    <SectionCard
      title="投放自動度"
      description="這是品牌層設定。預設為保守檔；放手檔要等平台寫入 API 開通後才會真的自動執行。"
    >
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
          description="要先建立品牌，才能設定投放自動度。"
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

          {cardState.status === "loading" && <Skeleton className="h-32" />}
          {cardState.status === "error" && (
            <EmptyState
              title="投放自動度讀取失敗"
              description={cardState.message}
              onAction={() => loadCard(brandId)}
              actionLabel="重新載入"
            />
          )}
          {cardState.status === "ready" && (
            <div className="flex flex-col gap-3" role="group" aria-label="投放自動度選項">
              <p className="text-sm text-muted-foreground">
                目前模式：
                <span className="font-medium text-foreground">
                  {MODES.find((mode) => mode.value === cardMode(cardState.card))?.label}
                </span>
              </p>
              <div className="grid gap-3 sm:grid-cols-2">
                {MODES.map((mode) => {
                  const selected = cardMode(cardState.card) === mode.value;
                  return (
                    <button
                      key={mode.value}
                      type="button"
                      aria-pressed={selected}
                      disabled={saveForm.saving}
                      onClick={() => void saveForm.submit(mode.value)}
                      className={`rounded-md border p-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                        selected
                          ? "border-primary bg-primary/10 text-foreground"
                          : "border-border text-muted-foreground hover:border-primary hover:text-foreground"
                      }`}
                    >
                      <span className="block text-sm font-semibold">{mode.label}</span>
                      <span className="mt-1 block text-xs">{mode.description}</span>
                    </button>
                  );
                })}
              </div>
              {saveForm.error && <p className="text-sm text-danger">{saveForm.error}</p>}
            </div>
          )}
        </>
      )}
    </SectionCard>
  );
}
