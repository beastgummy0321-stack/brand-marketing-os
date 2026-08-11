import { useState } from "react";
import { X } from "lucide-react";
import { SidePanel } from "@/components/layout/SidePanel";
import { createProductFact, PRODUCT_FACT_TYPES, updateProductFact, type ProductFact } from "@/lib/productsApi";
import { useFormSubmit } from "@/lib/useFormSubmit";
import { PanelSaveButton } from "../shared/PanelSaveButton";

/** 新增／編輯產品事實側板（契約 S6.24–S6.25）：編輯不改確認狀態，比照品牌智庫
 * `FactPanel.tsx` 同一份決策（決策 0013）。`fact` 傳 null＝新增。 */
export function FactPanel({
  brandId,
  productId,
  fact,
  onClose,
  onSaved,
}: {
  brandId: string;
  productId: string;
  fact: ProductFact | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const editing = fact !== null;
  const [factType, setFactType] = useState(fact?.fact_type ?? "");
  const [labelText, setLabelText] = useState(fact?.label ?? "");
  const [value, setValue] = useState(fact?.value ?? "");
  const [status, setStatus] = useState<"confirmed" | "pending">(fact?.status ?? "pending");
  const [sourceReference, setSourceReference] = useState(fact?.source_reference ?? "");

  const form = useFormSubmit(async () => {
    if (editing) {
      await updateProductFact(brandId, productId, fact.id, {
        fact_type: factType,
        label: labelText,
        value,
        source_reference: sourceReference,
      });
    } else {
      await createProductFact(brandId, productId, {
        fact_type: factType,
        label: labelText,
        value,
        status,
        source_reference: sourceReference,
      });
    }
    onSaved();
  });

  return (
    <SidePanel ariaLabel={editing ? "編輯產品事實" : "新增產品事實"} onClose={onClose}>
      <div className="flex items-start justify-between gap-3 border-b border-border pb-4">
        <h2 className="font-display text-lg text-foreground">{editing ? "編輯產品事實" : "新增產品事實"}</h2>
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
          <span className="font-medium text-foreground">這是哪一類事實？</span>
          <select
            value={factType}
            onChange={(e) => setFactType(e.target.value)}
            required
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          >
            <option value="" disabled>
              請選擇
            </option>
            {PRODUCT_FACT_TYPES.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">這條事實叫什麼？</span>
          <input
            type="text"
            value={labelText}
            onChange={(e) => setLabelText(e.target.value)}
            required
            placeholder="例如「主成分濃度」"
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">內容</span>
          <textarea
            value={value}
            onChange={(e) => setValue(e.target.value)}
            required
            rows={5}
            placeholder="寫得越具體，之後 AI 產出的內容就越貼近真實。"
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
        </label>

        {!editing && (
          <fieldset className="flex flex-col gap-2 text-sm">
            <legend className="font-medium text-foreground">這條已經確認過了嗎？</legend>
            <label className="flex items-center gap-2">
              <input
                type="radio"
                name="status"
                checked={status === "confirmed"}
                onChange={() => setStatus("confirmed")}
              />
              已確認
            </label>
            <label className="flex items-center gap-2">
              <input
                type="radio"
                name="status"
                checked={status === "pending"}
                onChange={() => setStatus("pending")}
              />
              待確認
            </label>
          </fieldset>
        )}

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">資料來源（選填{editing ? "，留空＝維持原來源" : ""}）</span>
          <input
            type="text"
            value={sourceReference}
            onChange={(e) => setSourceReference(e.target.value)}
            placeholder="例如「2025-03 客戶提供的產品型錄 p.4」"
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
        </label>

        {form.error && <p className="text-sm text-danger">{form.error}</p>}
        <div>
          <PanelSaveButton saving={form.saving} label={editing ? "儲存修改" : "新增這條事實"} />
        </div>
      </form>
    </SidePanel>
  );
}
