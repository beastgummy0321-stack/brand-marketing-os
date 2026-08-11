import { useState } from "react";
import { EmptyState } from "@/components/layout/EmptyState";
import { deleteFact, type LibraryBrandFact } from "@/lib/libraryApi";
import { Badge } from "../shared/Badge";
import { InlineDeleteButton } from "../shared/InlineDeleteButton";
import { FactConfirmPanel } from "../panels/FactConfirmPanel";
import { FactPanel } from "../panels/FactPanel";

type PanelState =
  | { mode: "closed" }
  | { mode: "new" }
  | { mode: "edit"; fact: LibraryBrandFact }
  | { mode: "confirm"; fact: LibraryBrandFact };

/** 品牌事實分頁（契約 S5.5–S5.13）：已確認／待確認兩段落，各自獨立判斷空狀態。 */
export function FactsTab({
  brandId,
  facts,
  onChanged,
}: {
  brandId: string;
  facts: LibraryBrandFact[];
  onChanged: () => void;
}) {
  const [panel, setPanel] = useState<PanelState>({ mode: "closed" });
  const confirmed = facts.filter((f) => f.status === "confirmed");
  const pending = facts.filter((f) => f.status === "pending");

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h2 className="font-display text-lg text-foreground">品牌事實</h2>
        <button
          type="button"
          onClick={() => setPanel({ mode: "new" })}
          className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90"
        >
          新增品牌事實
        </button>
      </div>

      <section className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold text-foreground">已確認（{confirmed.length}）</h3>
        {confirmed.length === 0 ? (
          <EmptyState
            title="這個品牌還沒有已確認的品牌事實"
            description="品牌事實是定位、受眾、語調這類長期資訊，是後面所有內容的依據。"
          />
        ) : (
          <ul className="flex flex-col gap-2">
            {confirmed.map((fact) => (
              <FactCard
                key={fact.id}
                fact={fact}
                brandId={brandId}
                onEdit={() => setPanel({ mode: "edit", fact })}
                onChanged={onChanged}
              />
            ))}
          </ul>
        )}
      </section>

      {pending.length > 0 && (
        <section className="flex flex-col gap-3">
          <h3 className="text-sm font-semibold text-foreground">待確認（{pending.length}）</h3>
          <p className="text-xs text-muted-foreground">這些內容還沒被確認，不會被系統當成事實使用。</p>
          <ul className="flex flex-col gap-2">
            {pending.map((fact) => (
              <FactCard
                key={fact.id}
                fact={fact}
                brandId={brandId}
                onEdit={() => setPanel({ mode: "edit", fact })}
                onConfirm={() => setPanel({ mode: "confirm", fact })}
                onChanged={onChanged}
              />
            ))}
          </ul>
        </section>
      )}

      {panel.mode === "new" && (
        <FactPanel
          brandId={brandId}
          fact={null}
          onClose={() => setPanel({ mode: "closed" })}
          onSaved={() => {
            setPanel({ mode: "closed" });
            onChanged();
          }}
        />
      )}
      {panel.mode === "edit" && (
        <FactPanel
          brandId={brandId}
          fact={panel.fact}
          onClose={() => setPanel({ mode: "closed" })}
          onSaved={() => {
            setPanel({ mode: "closed" });
            onChanged();
          }}
        />
      )}
      {panel.mode === "confirm" && (
        <FactConfirmPanel
          brandId={brandId}
          fact={panel.fact}
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

function FactCard({
  fact,
  brandId,
  onEdit,
  onConfirm,
  onChanged,
}: {
  fact: LibraryBrandFact;
  brandId: string;
  onEdit: () => void;
  onConfirm?: () => void;
  onChanged: () => void;
}) {
  return (
    <li className="flex flex-col gap-2 rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)]">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <Badge>{fact.fact_type_label}</Badge>
          {fact.stale_label && <Badge tone="warning">{fact.stale_label}</Badge>}
          <strong className="text-sm text-foreground">{fact.label}</strong>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          {onConfirm && (
            <button
              type="button"
              onClick={onConfirm}
              className="rounded-md border border-border px-2.5 py-1 text-xs font-medium text-foreground hover:border-primary hover:text-primary"
            >
              確認這條
            </button>
          )}
          <button type="button" onClick={onEdit} className="text-xs text-primary hover:underline">
            修改
          </button>
          <InlineDeleteButton
            confirmText={`確定要刪除「${fact.label}」？`}
            onDelete={async () => {
              await deleteFact(brandId, fact.id);
              onChanged();
            }}
          />
        </div>
      </div>
      <p className="text-sm text-foreground">{fact.value}</p>
      {fact.status === "confirmed" && (
        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer">詳細（確認人、確認時間、資料來源）</summary>
          <p className="mt-1">
            確認人：{fact.confirmed_by ?? "—"}
            <span className="mx-1.5" aria-hidden="true">
              ・
            </span>
            確認時間：{fact.confirmed_at ? fact.confirmed_at.slice(0, 10) : "—"}
            <span className="mx-1.5" aria-hidden="true">
              ・
            </span>
            資料來源：{fact.source_reference ?? "未填寫"}
          </p>
        </details>
      )}
    </li>
  );
}
