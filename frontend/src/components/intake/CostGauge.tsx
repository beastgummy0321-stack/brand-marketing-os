import { useState } from "react";
import type { IntakeDraft } from "@/lib/intakeApi";
import { DEFAULT_BUDGET } from "@/lib/intakeApi";

/** 右欄花費儀表（契約「任務流版型」節，S4.13／S4.67-70）：步驟 1 草稿還沒建立時顯示系統
 * 預設上限的靜態態，不可點「調整上限」；草稿建立後即時反映每次背景工作的花費變化。 */
export function CostGauge({ draft, onAdjust }: { draft: IntakeDraft | null; onAdjust: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const spent = draft?.cost_spent ?? 0;
  const limit = draft?.budget_limit ?? DEFAULT_BUDGET;
  const pct = limit > 0 ? Math.min(100, (spent / limit) * 100) : 0;
  const over = spent > limit;

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4 shadow-[var(--shadow-card)]">
      <p className="text-sm font-medium text-foreground">這次建檔的花費</p>
      <p className="text-lg font-semibold text-foreground">
        US$ {spent.toFixed(2)}
        <span className="ml-1 text-sm font-normal text-muted-foreground">／ US$ {limit.toFixed(2)} 上限</span>
      </p>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div className={`h-full rounded-full ${over ? "bg-danger" : "bg-primary"}`} style={{ width: `${pct}%` }} />
      </div>

      {draft && draft.cost_items.length > 0 && (
        <div className="flex flex-col gap-1 text-xs">
          <button type="button" onClick={() => setExpanded((v) => !v)} className="self-start text-primary hover:underline">
            {expanded ? "收起花費明細" : "展開花費明細"}
          </button>
          {expanded && (
            <ul className="flex flex-col gap-1 text-muted-foreground">
              {draft.cost_items.map((item, i) => (
                <li key={i} className="flex items-center justify-between gap-2">
                  <span>{item.label}</span>
                  <span className={item.failed ? "text-danger" : "text-foreground"}>
                    {item.failed ? "失敗，未計費" : `US$ ${item.amount.toFixed(2)}`}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <button
        type="button"
        disabled={!draft}
        onClick={onAdjust}
        className="self-start text-xs font-medium text-primary hover:underline disabled:cursor-not-allowed disabled:text-muted-foreground disabled:no-underline"
      >
        調整上限
      </button>
    </div>
  );
}
