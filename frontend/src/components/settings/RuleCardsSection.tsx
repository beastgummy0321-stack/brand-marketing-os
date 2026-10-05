import { useEffect, useRef, useState, type FormEvent } from "react";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import type { BrandOption, RuleCard } from "@/lib/settingsApi";
import { fetchBrandOptions, fetchRuleCards, resetRuleCard, saveRuleCard } from "@/lib/settingsApi";
import { typedValue } from "@/lib/typedNumber";
import { SectionCard } from "./shared/SectionCard";
import { SaveButton } from "./shared/SaveButton";
import { ApiResponseError } from "@/lib/http";
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
  const [selectedCard, setSelectedCard] = useState("");
  const cardRequest = useRef(0);
  const selectedBrandName = brandsState.status === "ready"
    ? brandsState.brands.find((brand) => brand.brand_id === brandId)?.brand_name
    : undefined;

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
    const request = ++cardRequest.current;
    setCardsState({ status: "loading" });
    fetchRuleCards(id)
      .then((data) => { if (request === cardRequest.current) setCardsState({ status: "ready", cards: data.cards }); })
      .catch((err: unknown) =>
        request === cardRequest.current &&
        setCardsState({
          status: "error",
          message: err instanceof Error ? err.message : "規則卡讀取失敗，請稍後再試。",
        }),
      );
  }

  useEffect(() => {
    setSelectedCard("");
    if (brandId) loadCards(brandId);
    else setCardsState({ status: "idle" });
    return () => { cardRequest.current += 1; };
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
            <div className="flex flex-col gap-4">
              {Array.from({ length: 2 }, (_, i) => (
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
            <div className="flex flex-col gap-4">
              {cardsState.cards.length === 0 ? <EmptyState title="目前沒有規則卡" description="這個品牌還沒有可調整的規則參數。" /> : <>
                <p className="text-xs text-muted-foreground">作用品牌：<span className="font-medium text-foreground">{selectedBrandName}</span></p>
                <label className="flex max-w-sm flex-col gap-1.5 text-sm">
                  <span className="font-medium">選擇規則卡</span>
                  <select value={cardsState.cards.some((card) => card.key === selectedCard) ? selectedCard : cardsState.cards[0].key} onChange={(event) => setSelectedCard(event.target.value)}>
                    {cardsState.cards.map((card) => <option key={card.key} value={card.key}>{card.title}</option>)}
                  </select>
                </label>
                {cardsState.cards.map((card) => (
                  <div key={`${brandId}:${card.key}`} hidden={card.key !== (cardsState.cards.some((candidate) => candidate.key === selectedCard) ? selectedCard : cardsState.cards[0].key)}>
                    <RuleCardItem brandId={brandId} card={card} onUpdated={handleCardUpdated} />
                  </div>
                ))}
              </>}
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

  /** The server's refusal of each field (its `field_errors`), shown under that field. */
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  // F47-I03 / F50 Contract I: send what was typed, as text (the server parses it). A field left empty is
  // not sent (the server reads a missing field as empty and refuses it with that field's sentence).
  const saveForm = useFormSubmit(async () => {
    setFieldErrors({});
    const typed: Record<string, string> = {};
    for (const [key, raw] of Object.entries(values)) {
      const value = typedValue(raw);
      if (value !== null) typed[key] = value;
    }
    try {
      onUpdated(await saveRuleCard(brandId, card.key, typed));
    } catch (err) {
      if (err instanceof ApiResponseError) setFieldErrors(err.fieldErrors);
      throw err;
    }
  });

  const resetForm = useFormSubmit(async () => {
    const updated = await resetRuleCard(brandId, card.key);
    setFieldErrors({});
    saveForm.clearError();
    setValues(Object.fromEntries(updated.fields.map((f) => [f.key, String(f.value)])));
    onUpdated(updated);
  });

  function fieldChanged(event: FormEvent<HTMLFormElement>) {
    saveForm.formProps.onChange(event);
    resetForm.clearError();
    setFieldErrors({});
  }
  // A form-level line only when it says something the fields do not (the server's `error` is
  // normally the first field's sentence, already shown under that field).
  const formError = saveForm.error && !Object.values(fieldErrors).includes(saveForm.error) ? saveForm.error : null;

  function handleReset() {
    if (window.confirm(`確定要重設整張「${card.title}」？這會把這張卡的所有欄位重設回系統預設值。`)) {
      void resetForm.submit();
    }
  }

  return (
    <div className="flex max-w-[var(--width-form)] flex-col gap-4 border-t border-border pt-5">
      <div>
        <h3 className="text-sm font-semibold text-foreground">{card.title}</h3>
        <p className="mt-1 text-xs text-muted-foreground">{card.description}</p>
      </div>
      <form
        className="flex flex-col gap-3"
        onChange={fieldChanged}
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
                aria-invalid={fieldErrors[f.key] ? true : undefined}
                onChange={(e) => setValues((prev) => ({ ...prev, [f.key]: e.target.value }))}
                className="w-full rounded-md border border-border px-2 py-1.5 text-sm text-foreground"
              />
              <span className="shrink-0 text-muted-foreground">{f.unit}</span>
            </div>
            <span className="text-muted-foreground">{f.help}</span>
            {fieldErrors[f.key] && <span role="alert" className="text-danger">{fieldErrors[f.key]}</span>}
          </label>
        ))}
        {formError && <p role="alert" className="text-xs text-danger">{formError}</p>}
        {resetForm.error && <p className="text-xs text-danger">{resetForm.error}</p>}
        <div className="flex items-center gap-2">
          <SaveButton saving={saveForm.saving} label="儲存這張卡" />
          <button
            type="button"
            onClick={handleReset}
            disabled={resetForm.saving}
            className="rounded-md border border-border px-3 py-2 text-xs font-medium text-muted-foreground hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
          >
            {resetForm.saving ? "正在重設整張卡…" : "重設整張卡"}
          </button>
        </div>
      </form>
    </div>
  );
}
