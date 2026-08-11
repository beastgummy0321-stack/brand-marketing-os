import { useState } from "react";
import { X } from "lucide-react";
import { SidePanel } from "@/components/layout/SidePanel";
import {
  BRAND_FACT_TYPES,
  createFact,
  updateFact,
  type LibraryBrandFact,
} from "@/lib/libraryApi";
import { useFormSubmit } from "@/lib/useFormSubmit";
import { PanelSaveButton } from "../shared/PanelSaveButton";

/** 新增／編輯品牌事實側板（契約 S5.12）：編輯不能改狀態，比照舊版 `fact_new.html` 編輯
 * 模式沒有狀態欄位。`fact` 傳 null＝新增。 */
export function FactPanel({
  brandId,
  fact,
  onClose,
  onSaved,
}: {
  brandId: string;
  fact: LibraryBrandFact | null;
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
      await updateFact(brandId, fact.id, {
        fact_type: factType,
        label: labelText,
        value,
        source_reference: sourceReference,
      });
    } else {
      await createFact(brandId, {
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
    <SidePanel ariaLabel={editing ? "編輯品牌事實" : "新增品牌事實"} onClose={onClose}>
      <div className="flex items-start justify-between gap-3 border-b border-border pb-4">
        <h2 className="font-display text-lg text-foreground">{editing ? "編輯品牌事實" : "新增品牌事實"}</h2>
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
            {BRAND_FACT_TYPES.map(([v, l]) => (
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
            placeholder="例如「主要購買者輪廓」"
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
            placeholder="例如「2025-03 客戶提供的品牌手冊 p.12」"
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
