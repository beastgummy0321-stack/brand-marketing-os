import { useState } from "react";
import { X } from "lucide-react";
import { SidePanel } from "@/components/layout/SidePanel";
import type { IntakeDraft } from "@/lib/intakeApi";
import { saveBudget } from "@/lib/intakeApi";
import { useFormSubmit } from "@/lib/useFormSubmit";
import { AI_COST_NOTE } from "./CostGauge";

/** 花費上限側板（契約 S4.67-70）。 */
export function BudgetPanel({
  brandId,
  draft,
  onClose,
  onSaved,
}: {
  brandId: string;
  draft: IntakeDraft;
  onClose: () => void;
  onSaved: (limit: number) => void;
}) {
  const [limit, setLimit] = useState(String(draft.budget_limit));
  const { saving, error, submit } = useFormSubmit(async () => {
    const value = Number(limit);
    await saveBudget(brandId, value);
    onSaved(value);
    onClose();
  });

  return (
    <SidePanel ariaLabel="這次建檔最多可以花多少" onClose={onClose}>
      <div className="flex items-start justify-between gap-3 border-b border-border pb-4">
        <div>
          <h2 className="font-display text-lg text-foreground">這次建檔最多可以花多少？</h2>
          <p className="mt-1 text-sm text-muted-foreground">只管這個品牌這一次。用不完不會累積。{AI_COST_NOTE}</p>
        </div>
        <button type="button" onClick={onClose} aria-label="關閉側板" className="rounded-md p-2 text-muted-foreground hover:bg-muted">
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>

      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">上限金額</span>
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground">US$</span>
            <input
              type="text"
              inputMode="decimal"
              value={limit}
              onChange={(e) => setLimit(e.target.value)}
              className="w-full rounded-md border border-border px-3 py-2 text-sm text-foreground"
            />
          </div>
          <span className="text-xs text-muted-foreground">目前已花費 US$ {draft.cost_spent.toFixed(2)}，上限不能設得比它低。{AI_COST_NOTE}</span>
        </label>

        {error && <p className="text-sm text-danger">{error}</p>}

        <button
          type="submit"
          disabled={saving}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saving ? "儲存中…" : "存起來"}
        </button>
      </form>
    </SidePanel>
  );
}
