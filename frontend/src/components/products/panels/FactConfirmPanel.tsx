import { useState } from "react";
import { X } from "lucide-react";
import { SidePanel } from "@/components/layout/SidePanel";
import { confirmProductFact, type ProductFact } from "@/lib/productsApi";
import { useFormSubmit } from "@/lib/useFormSubmit";
import { PanelSaveButton } from "../shared/PanelSaveButton";

/** 確認產品事實側板（契約 S6.26）：唯讀顯示名稱／內容，只填「確認人」。 */
export function FactConfirmPanel({
  brandId,
  productId,
  fact,
  onClose,
  onSaved,
}: {
  brandId: string;
  productId: string;
  fact: ProductFact;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [confirmedBy, setConfirmedBy] = useState("");
  const form = useFormSubmit(async () => {
    await confirmProductFact(brandId, productId, fact.id, confirmedBy);
    onSaved();
  });

  return (
    <SidePanel ariaLabel="確認這條產品事實" onClose={onClose}>
      <div className="flex items-start justify-between gap-3 border-b border-border pb-4">
        <h2 className="font-display text-lg text-foreground">確認這條產品事實</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="關閉側板"
          className="rounded-md p-2 text-muted-foreground hover:bg-muted"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
      <p className="text-sm text-muted-foreground">
        確認之後，這條內容就會被系統當成產品事實使用。確認紀錄會留存，之後可以查到是誰、什麼時候確認的。
      </p>
      <dl className="flex flex-col gap-2 rounded-md border border-border bg-muted/40 p-3 text-sm">
        <div className="flex gap-2">
          <dt className="shrink-0 text-muted-foreground">類型</dt>
          <dd className="text-foreground">{fact.fact_type_label}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="shrink-0 text-muted-foreground">名稱</dt>
          <dd className="text-foreground">{fact.label}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="shrink-0 text-muted-foreground">內容</dt>
          <dd className="text-foreground">{fact.value}</dd>
        </div>
      </dl>
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          void form.submit();
        }}
      >
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
          <PanelSaveButton saving={form.saving} label="確認這條事實" pendingLabel="處理中…" />
        </div>
      </form>
    </SidePanel>
  );
}
