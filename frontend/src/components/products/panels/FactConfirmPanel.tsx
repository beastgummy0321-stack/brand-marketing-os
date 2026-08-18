import { X } from "lucide-react";
import { SidePanel } from "@/components/layout/SidePanel";
import { confirmProductFact, type ProductFact } from "@/lib/productsApi";
import { useFormSubmit } from "@/lib/useFormSubmit";
import { PanelSaveButton } from "../shared/PanelSaveButton";

/** 確認產品事實側板（T2 條文 2.5）：單機單人，確認人由後端自動記為使用者。 */
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
  const form = useFormSubmit(async () => {
    await confirmProductFact(brandId, productId, fact.id);
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
        確認之後，這條內容就會被系統當成產品事實使用；系統會自動留下這次確認紀錄。
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
        {form.error && <p className="text-sm text-danger">{form.error}</p>}
        <div>
          <PanelSaveButton saving={form.saving} label="確認這條事實" pendingLabel="處理中…" />
        </div>
      </form>
    </SidePanel>
  );
}
