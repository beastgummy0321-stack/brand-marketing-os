import { useMemo, useState, type ReactNode } from "react";
import { EmptyState } from "@/components/layout/EmptyState";
import { Pager } from "@/components/layout/Pager";
import { VisualSpecWarnings } from "@/components/workbench";
import { deleteFact, type LibraryBrandFact } from "@/lib/libraryApi";
import { usePagination } from "@/lib/usePagination";
import { cn } from "@/lib/utils";
import { Badge } from "../shared/Badge";
import { InlineDeleteButton } from "../shared/InlineDeleteButton";
import { FactConfirmPanel } from "../panels/FactConfirmPanel";
import { FactPanel } from "../panels/FactPanel";

type PanelState =
  | { mode: "closed" }
  | { mode: "new" }
  | { mode: "edit"; fact: LibraryBrandFact }
  | { mode: "confirm"; fact: LibraryBrandFact };

/** 品牌事實分頁（契約 S5.5–S5.13）：已確認／待確認兩段落，各自獨立判斷空狀態、各自分頁
 * （互動鐵則⑥）。類型篩選 chips 聚合自資料裡出現過的 fact_type，不硬編清單。 */
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
  const [typeFilter, setTypeFilter] = useState<string | null>(null);

  const types = useMemo(() => {
    const seen = new Map<string, string>();
    for (const f of facts) if (!seen.has(f.fact_type)) seen.set(f.fact_type, f.fact_type_label);
    return [...seen.entries()];
  }, [facts]);

  const filtered = typeFilter ? facts.filter((f) => f.fact_type === typeFilter) : facts;
  const confirmed = filtered.filter((f) => f.status === "confirmed");
  const pending = filtered.filter((f) => f.status === "pending");

  const confirmedPage = usePagination(confirmed);
  const pendingPage = usePagination(pending);

  function selectType(type: string | null) {
    setTypeFilter(type);
    confirmedPage.resetPage();
    pendingPage.resetPage();
  }

  return (
    <div className="flex flex-col gap-6">
      <VisualSpecWarnings brandId={brandId} />

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

      {types.length > 1 && (
        <div className="flex flex-wrap gap-2">
          <FilterChip active={typeFilter === null} onClick={() => selectType(null)}>
            全部
          </FilterChip>
          {types.map(([type, label]) => (
            <FilterChip key={type} active={typeFilter === type} onClick={() => selectType(type)}>
              {label}
            </FilterChip>
          ))}
        </div>
      )}

      <section ref={confirmedPage.topRef} className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold text-foreground">已確認（{confirmed.length}）</h3>
        {confirmed.length === 0 ? (
          <EmptyState
            title="這個品牌還沒有已確認的品牌事實"
            description="品牌事實是定位、受眾、語調這類長期資訊，是後面所有內容的依據。"
          />
        ) : (
          <>
            <ul className="flex flex-col gap-2">
              {confirmedPage.pageItems.map((fact) => (
                <FactCard
                  key={fact.id}
                  fact={fact}
                  brandId={brandId}
                  onEdit={fact.fact_type === "policy" ? undefined : () => setPanel({ mode: "edit", fact })}
                  onChanged={onChanged}
                />
              ))}
            </ul>
            <Pager
              page={confirmedPage.page}
              pageCount={confirmedPage.pageCount}
              totalCount={confirmedPage.totalCount}
              onChange={confirmedPage.goToPage}
            />
          </>
        )}
      </section>

      {pending.length > 0 && (
        <section ref={pendingPage.topRef} className="flex flex-col gap-3">
          <h3 className="text-sm font-semibold text-foreground">待確認（{pending.length}）</h3>
          <p className="text-xs text-muted-foreground">這些內容還沒被確認，不會被系統當成事實使用。</p>
          <ul className="flex flex-col gap-2">
            {pendingPage.pageItems.map((fact) => (
              <FactCard
                key={fact.id}
                fact={fact}
                brandId={brandId}
                onEdit={fact.fact_type === "policy" ? undefined : () => setPanel({ mode: "edit", fact })}
                onConfirm={() => setPanel({ mode: "confirm", fact })}
                onChanged={onChanged}
              />
            ))}
          </ul>
          <Pager
            page={pendingPage.page}
            pageCount={pendingPage.pageCount}
            totalCount={pendingPage.totalCount}
            onChange={pendingPage.goToPage}
          />
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

function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-full border px-3 py-1 text-xs font-medium",
        active
          ? "border-primary bg-primary text-primary-foreground"
          : "border-border text-muted-foreground hover:border-primary hover:text-primary",
      )}
    >
      {children}
    </button>
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
  /** Absent for 「全店政策」: policies are edited in brand onboarding only (F42-I01). */
  onEdit?: () => void;
  onConfirm?: () => void;
  onChanged: () => void;
}) {
  return (
    <li className="flex flex-col gap-2 rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)]">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <Badge>{fact.fact_type_label}</Badge>
          {/* F42-I01: a policy's key is internal; its Chinese name is already the label. */}
          {fact.fact_type === "proof" && fact.fact_key_label && (
            <span className="text-xs text-muted-foreground">{fact.fact_key_label}</span>
          )}
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
          {onEdit && (
            <button type="button" onClick={onEdit} className="text-xs text-primary hover:underline">
              修改
            </button>
          )}
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
