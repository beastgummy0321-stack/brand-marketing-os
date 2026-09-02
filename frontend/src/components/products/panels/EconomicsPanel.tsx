import { useState } from "react";
import { X } from "lucide-react";
import { SidePanel } from "@/components/layout/SidePanel";
import { CURRENCIES, saveProductEconomics, type ProductEconomics } from "@/lib/productsApi";
import { useFormSubmit } from "@/lib/useFormSubmit";
import { PanelSaveButton } from "../shared/PanelSaveButton";

/** 新增／更新產品經濟數字側板（契約 S6.33）：售價必填，其餘數字欄位預設 0。 */
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
  const [fixedCost, setFixedCost] = useState(String(economics?.fixed_cost ?? 0));
  const [unitVariableCost, setUnitVariableCost] = useState(String(economics?.unit_variable_cost ?? 0));
  const [shippingCost, setShippingCost] = useState(String(economics?.shipping_cost ?? 0));
  const [currency, setCurrency] = useState(economics?.currency ?? CURRENCIES[0][0]);
  const [confirmedBy, setConfirmedBy] = useState(economics?.confirmed_by ?? "");

  const form = useFormSubmit(async () => {
    await saveProductEconomics(brandId, productId, {
      selling_price: Number(sellingPrice) || 0,
      fixed_cost: Number(fixedCost) || 0,
      unit_variable_cost: Number(unitVariableCost) || 0,
      shipping_cost: Number(shippingCost) || 0,
      currency,
      // ADR 0053 §5：生效日一律是今天，這裡不再收使用者輸入，固定送空字串（後端視為未填）。
      effective_from: "",
      confirmed_by: confirmedBy,
    });
    onSaved();
  });

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
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-foreground">固定成本</span>
            <input
              type="number"
              step="0.01"
              value={fixedCost}
              onChange={(e) => setFixedCost(e.target.value)}
              className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-foreground">單位變動成本</span>
            <input
              type="number"
              step="0.01"
              value={unitVariableCost}
              onChange={(e) => setUnitVariableCost(e.target.value)}
              className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
            />
          </label>
        </div>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">運費（可填負數表示折抵）</span>
          <input
            type="number"
            step="0.01"
            value={shippingCost}
            onChange={(e) => setShippingCost(e.target.value)}
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
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
        {form.error && <p className="text-sm text-danger">{form.error}</p>}
        <div>
          <PanelSaveButton saving={form.saving} label={editing ? "儲存修改" : "儲存這筆經濟數字"} />
        </div>
      </form>
    </SidePanel>
  );
}
