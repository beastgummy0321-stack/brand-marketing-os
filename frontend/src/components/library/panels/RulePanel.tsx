import { useState } from "react";
import { X } from "lucide-react";
import { SidePanel } from "@/components/layout/SidePanel";
import {
  createRule,
  RULE_TYPES,
  updateRule,
  type LibraryProductOption,
  type LibraryRule,
  type RuleSeverity,
} from "@/lib/libraryApi";
import { useFormSubmit } from "@/lib/useFormSubmit";
import { PanelSaveButton } from "../shared/PanelSaveButton";

/** 新增／編輯限制規則側板（契約 S5.17）。`rule` 傳 null＝新增。 */
export function RulePanel({
  brandId,
  rule,
  products,
  onClose,
  onSaved,
}: {
  brandId: string;
  rule: LibraryRule | null;
  products: LibraryProductOption[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const editing = rule !== null;
  const [ruleType, setRuleType] = useState(rule?.rule_type ?? "");
  const [content, setContent] = useState(rule?.content ?? "");
  const [severity, setSeverity] = useState<RuleSeverity>(rule?.severity ?? "hard");
  const [productId, setProductId] = useState(rule?.product_id ?? "");
  const [sourceReference, setSourceReference] = useState(rule?.source_reference ?? "");

  const form = useFormSubmit(async () => {
    const fields = { rule_type: ruleType, content, severity, product_id: productId, source_reference: sourceReference };
    if (editing) await updateRule(brandId, rule.id, fields);
    else await createRule(brandId, fields);
    onSaved();
  });

  return (
    <SidePanel ariaLabel={editing ? "編輯限制規則" : "新增限制規則"} onClose={onClose}>
      <div className="flex items-start justify-between gap-3 border-b border-border pb-4">
        <h2 className="font-display text-lg text-foreground">{editing ? "編輯限制規則" : "新增限制規則"}</h2>
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
          <span className="font-medium text-foreground">這是哪一種規則？</span>
          <select
            value={ruleType}
            onChange={(e) => setRuleType(e.target.value)}
            required
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          >
            <option value="" disabled>
              請選擇
            </option>
            {RULE_TYPES.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">規則內容</span>
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            required
            rows={4}
            placeholder="寫清楚具體禁止或要求的做法，越具體越好判斷。"
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
        </label>

        <fieldset className="flex flex-col gap-2 text-sm">
          <legend className="font-medium text-foreground">違反的後果有多嚴重？</legend>
          <label className="flex items-center gap-2">
            <input type="radio" name="severity" checked={severity === "hard"} onChange={() => setSeverity("hard")} />
            必須遵守
          </label>
          <label className="flex items-center gap-2">
            <input type="radio" name="severity" checked={severity === "soft"} onChange={() => setSeverity("soft")} />
            建議遵守
          </label>
        </fieldset>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">適用範圍</span>
          <select
            value={productId}
            onChange={(e) => setProductId(e.target.value)}
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          >
            <option value="">整個品牌</option>
            {products.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">資料來源（選填）</span>
          <input
            type="text"
            value={sourceReference}
            onChange={(e) => setSourceReference(e.target.value)}
            placeholder="例如「2025-03 客戶提供的品牌手冊」"
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
        </label>

        {form.error && <p className="text-sm text-danger">{form.error}</p>}
        <div>
          <PanelSaveButton saving={form.saving} label={editing ? "儲存修改" : "新增這條限制規則"} />
        </div>
      </form>
    </SidePanel>
  );
}
