import { useState } from "react";
import { EmptyState } from "@/components/layout/EmptyState";
import { deleteRule, type LibraryProductOption, type LibraryRule } from "@/lib/libraryApi";
import { Badge } from "../shared/Badge";
import { InlineDeleteButton } from "../shared/InlineDeleteButton";
import { RulePanel } from "../panels/RulePanel";

type PanelState = { mode: "closed" } | { mode: "new" } | { mode: "edit"; rule: LibraryRule };

/** 限制規則分頁（契約 S5.14–S5.18）：單一清單，不分段。 */
export function RulesTab({
  brandId,
  rules,
  products,
  onChanged,
}: {
  brandId: string;
  rules: LibraryRule[];
  products: LibraryProductOption[];
  onChanged: () => void;
}) {
  const [panel, setPanel] = useState<PanelState>({ mode: "closed" });

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="font-display text-lg text-foreground">限制規則</h2>
        <button
          type="button"
          onClick={() => setPanel({ mode: "new" })}
          className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90"
        >
          新增限制規則
        </button>
      </div>

      {rules.length === 0 ? (
        <EmptyState title="還沒有任何限制規則" description="規則是產出內容時不能踩的線，例如禁用字詞、素材使用規定。" />
      ) : (
        <div className="overflow-x-auto rounded-md border border-border">
          <table className="w-full text-left text-sm">
            <thead className="bg-muted text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">嚴重度</th>
                <th className="px-3 py-2 font-medium">類型</th>
                <th className="px-3 py-2 font-medium">內容</th>
                <th className="px-3 py-2 font-medium">適用範圍</th>
                <th className="px-3 py-2 font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {rules.map((rule) => (
                <tr key={rule.id} className="border-t border-border align-top">
                  <td className="whitespace-nowrap px-3 py-2">
                    <Badge tone={rule.severity === "hard" ? "danger" : "neutral"}>
                      {rule.severity === "hard" ? "必須遵守" : "建議遵守"}
                    </Badge>
                  </td>
                  <td className="whitespace-nowrap px-3 py-2">
                    <Badge>{rule.rule_type_label}</Badge>
                  </td>
                  <td className="px-3 py-2 text-foreground">{rule.content}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">{rule.scope_label}</td>
                  <td className="whitespace-nowrap px-3 py-2">
                    <div className="flex items-center gap-3">
                      <button
                        type="button"
                        onClick={() => setPanel({ mode: "edit", rule })}
                        className="text-xs text-primary hover:underline"
                      >
                        修改
                      </button>
                      <InlineDeleteButton
                        confirmText="確定要刪除這條規則？"
                        onDelete={async () => {
                          await deleteRule(brandId, rule.id);
                          onChanged();
                        }}
                      />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {(panel.mode === "new" || panel.mode === "edit") && (
        <RulePanel
          brandId={brandId}
          rule={panel.mode === "edit" ? panel.rule : null}
          products={products}
          onClose={() => setPanel({ mode: "closed" })}
          onSaved={() => {
            setPanel({ mode: "closed" });
            onChanged();
          }}
        />
      )}
    </div>
  );
}
