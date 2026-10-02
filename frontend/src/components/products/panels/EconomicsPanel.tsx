import { useState, type FormEvent } from "react";
import { X } from "lucide-react";
import { SidePanel } from "@/components/layout/SidePanel";
import { ApiResponseError } from "@/lib/http";
import {
  CURRENCIES,
  saveProductEconomics,
  type AssumptionField,
  type ProductEconomics,
} from "@/lib/productsApi";
import { useFormSubmit } from "@/lib/useFormSubmit";
import { PanelSaveButton } from "../shared/PanelSaveButton";

type NumberField = "selling_price" | "fixed_cost" | "unit_variable_cost" | "shipping_cost";

/** What was typed, as sent (F47 Contract A): empty = `null` (unset), never 0 and never clamped. */
function typed(raw: string): number | null {
  return raw.trim() === "" ? null : Number(raw);
}

/** 新增／更新產品經濟數字側板（契約 S6.33）：售價必填，三個成本留空＝未填（送 null，不補 0）。
 * F47-I03: a refused number shows the server's sentence under its own field (the route's
 * `field_errors`); every message clears as soon as any field changes. */
export function EconomicsPanel({
  brandId,
  productId,
  economics,
  onClose,
  onSaved,
}: {
  brandId: string;
  productId: string;
  economics: ProductEconomics | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const editing = economics !== null;
  const [sellingPrice, setSellingPrice] = useState(String(economics?.selling_price ?? ""));
  const [fixedCost, setFixedCost] = useState(String(economics?.fixed_cost ?? ""));
  const [unitVariableCost, setUnitVariableCost] = useState(String(economics?.unit_variable_cost ?? ""));
  const [shippingCost, setShippingCost] = useState(String(economics?.shipping_cost ?? ""));
  const [currency, setCurrency] = useState(economics?.currency ?? CURRENCIES[0][0]);
  const [confirmedBy, setConfirmedBy] = useState(economics?.confirmed_by ?? "");
  const [closeRate, setCloseRate] = useState(economics?.close_rate == null ? "" : String(economics.close_rate));
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<NumberField, string>>>({});
  // 使用者手改一個欄位時，那一欄不再是假設值（decision 17）——編輯任何欄位都會把它從
  // assumptions 移掉，不分是不是「假設值」原本掛的那個欄位，因為使用者已經看過並確認過整組數字。
  const [assumptions, setAssumptions] = useState<AssumptionField[]>(economics?.assumptions ?? []);
  const dropAssumption = (field: AssumptionField) =>
    setAssumptions((prev) => prev.filter((f) => f !== field));

  const form = useFormSubmit(async () => {
    setFieldErrors({});
    try {
      await saveProductEconomics(brandId, productId, {
        selling_price: typed(sellingPrice),
        fixed_cost: typed(fixedCost),
        unit_variable_cost: typed(unitVariableCost),
        shipping_cost: typed(shippingCost),
        currency,
        // ADR 0053 §5：生效日一律是今天，這裡不再收使用者輸入，固定送空字串（後端視為未填）。
        effective_from: "",
        confirmed_by: confirmedBy,
        close_rate: typed(closeRate),
        assumptions,
      });
    } catch (err) {
      if (err instanceof ApiResponseError) setFieldErrors(err.fieldErrors);
      throw err;
    }
    onSaved();
  });
  const shownUnderField = Object.values(fieldErrors).some(Boolean);

  function fieldChanged(event: FormEvent<HTMLFormElement>) {
    form.formProps.onChange(event);
    setFieldErrors({});
  }

  return (
    <SidePanel ariaLabel={editing ? "更新產品經濟數字" : "填寫產品經濟數字"} onClose={onClose}>
      <div className="flex items-start justify-between gap-3 border-b border-border pb-4">
        <h2 className="font-display text-lg text-foreground">{editing ? "更新產品經濟數字" : "填寫產品經濟數字"}</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="關閉側板"
          className="rounded-md p-2 text-muted-foreground hover:bg-muted"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
      <form
        className="flex flex-col gap-4"
        onChange={fieldChanged}
        onSubmit={(e) => {
          e.preventDefault();
          void form.submit();
        }}
      >
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">售價</span>
          <input
            type="number"
            step="0.01"
            value={sellingPrice}
            onChange={(e) => setSellingPrice(e.target.value)}
            required
            aria-invalid={fieldErrors.selling_price ? true : undefined}
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
          <FieldError message={fieldErrors.selling_price} />
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-foreground">固定成本</span>
            <input
              type="number"
              step="0.01"
              value={fixedCost}
              onChange={(e) => setFixedCost(e.target.value)}
              aria-invalid={fieldErrors.fixed_cost ? true : undefined}
              className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
            />
            <span className="text-xs text-muted-foreground">每月不管賣幾件都要付的錢。</span>
            <FieldError message={fieldErrors.fixed_cost} />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-foreground">單位變動成本</span>
            <input
              type="number"
              step="0.01"
              value={unitVariableCost}
              onChange={(e) => {
                setUnitVariableCost(e.target.value);
                dropAssumption("cost");
              }}
              aria-invalid={fieldErrors.unit_variable_cost ? true : undefined}
              className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
            />
            <span className="text-xs text-muted-foreground">每賣一件多花的錢。</span>
            <FieldError message={fieldErrors.unit_variable_cost} />
          </label>
        </div>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">運費</span>
          <input
            type="number"
            step="0.01"
            value={shippingCost}
            onChange={(e) => {
              setShippingCost(e.target.value);
              dropAssumption("shipping");
            }}
            aria-invalid={fieldErrors.shipping_cost ? true : undefined}
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
          <FieldError message={fieldErrors.shipping_cost} />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">成交率（選填）</span>
          <input
            type="number"
            step="0.01"
            min="0.01"
            max="1"
            value={closeRate}
            onChange={(e) => {
              setCloseRate(e.target.value);
              dropAssumption("close_rate");
            }}
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
          <span className="text-xs text-muted-foreground">
            留空＝賣一次算一次轉換。0.2 代表五筆名單成交一筆。
          </span>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">幣別</span>
          <select
            value={currency}
            onChange={(e) => setCurrency(e.target.value)}
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          >
            {CURRENCIES.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">確認人是誰？</span>
          <input
            type="text"
            value={confirmedBy}
            onChange={(e) => setConfirmedBy(e.target.value)}
            required
            placeholder="例如「小陳」"
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
        </label>
        {form.error && !shownUnderField && <p role="alert" className="text-sm text-danger">{form.error}</p>}
        <div>
          <PanelSaveButton saving={form.saving} label={editing ? "儲存修改" : "儲存這筆經濟數字"} />
        </div>
      </form>
    </SidePanel>
  );
}

function FieldError({ message }: { message: string | undefined }) {
  return message ? <span role="alert" className="text-xs text-danger">{message}</span> : null;
}
