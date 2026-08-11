import { useState } from "react";
import { TriangleAlert } from "lucide-react";
import { EmptyState } from "@/components/layout/EmptyState";
import { Pager } from "@/components/layout/Pager";
import { deleteClaim, type ClaimType, type LibraryClaim, type LibraryProductOption } from "@/lib/libraryApi";
import { usePagination } from "@/lib/usePagination";
import { InlineDeleteButton } from "../shared/InlineDeleteButton";
import { ClaimPanel } from "../panels/ClaimPanel";

type PanelState = { mode: "closed" } | { mode: "new" } | { mode: "edit"; claim: LibraryClaim };

const GROUPS: { type: ClaimType; title: string }[] = [
  { type: "approved", title: "可用" },
  { type: "high_risk", title: "高風險" },
  { type: "forbidden", title: "禁用" },
];

/** 宣稱分頁（契約 S5.19–S5.22）：三段分類，各自筆數為 0 時該段不顯示，各自超過 12 筆分頁
 * （互動鐵則⑥）。 */
export function ClaimsTab({
  brandId,
  claims,
  products,
  onChanged,
}: {
  brandId: string;
  claims: LibraryClaim[];
  products: LibraryProductOption[];
  onChanged: () => void;
}) {
  const [panel, setPanel] = useState<PanelState>({ mode: "closed" });

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h2 className="font-display text-lg text-foreground">宣稱</h2>
        <button
          type="button"
          onClick={() => setPanel({ mode: "new" })}
          className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90"
        >
          新增宣稱
        </button>
      </div>

      {claims.length === 0 ? (
        <EmptyState title="還沒有登錄任何宣稱" description="建議至少先把不能講的話寫進來，避免之後的產出踩到法規紅線。" />
      ) : (
        GROUPS.map(({ type, title }) => {
          const group = claims.filter((c) => c.claim_type === type);
          if (group.length === 0) return null;
          return (
            <ClaimGroupSection
              key={type}
              type={type}
              title={title}
              group={group}
              brandId={brandId}
              onEdit={(claim) => setPanel({ mode: "edit", claim })}
              onChanged={onChanged}
            />
          );
        })
      )}

      {(panel.mode === "new" || panel.mode === "edit") && (
        <ClaimPanel
          brandId={brandId}
          claim={panel.mode === "edit" ? panel.claim : null}
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

function ClaimGroupSection({
  type,
  title,
  group,
  brandId,
  onEdit,
  onChanged,
}: {
  type: ClaimType;
  title: string;
  group: LibraryClaim[];
  brandId: string;
  onEdit: (claim: LibraryClaim) => void;
  onChanged: () => void;
}) {
  const { page, pageCount, totalCount, pageItems, goToPage, topRef } = usePagination(group);

  return (
    <section ref={topRef} className="flex flex-col gap-2">
      <h3 className="text-sm font-semibold text-foreground">
        {title}（{group.length}）
      </h3>
      <ul className="flex flex-col gap-2">
        {pageItems.map((claim) => (
          <li
            key={claim.id}
            className="flex flex-col gap-1 rounded-md border border-border bg-card p-3 text-sm shadow-[var(--shadow-card)]"
          >
            <p className="flex flex-wrap items-center gap-1.5 text-foreground">
              {claim.claim_text}
              {type === "high_risk" && !claim.evidence_source_reference && (
                <span className="inline-flex items-center gap-1 text-xs font-medium text-danger">
                  <TriangleAlert className="h-3.5 w-3.5" aria-hidden="true" />
                  尚未附上佐證來源
                </span>
              )}
            </p>
            <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
              {type === "approved" && (
                <>
                  {claim.evidence_source_reference ? `佐證：${claim.evidence_source_reference}` : "尚未填寫佐證來源"}
                  <span aria-hidden="true">・</span>
                </>
              )}
              適用：{claim.scope_label}
              <span aria-hidden="true">・</span>
              <button type="button" onClick={() => onEdit(claim)} className="text-primary hover:underline">
                修改
              </button>
              <span aria-hidden="true">・</span>
              <InlineDeleteButton
                confirmText="確定要刪除這條宣稱？"
                onDelete={async () => {
                  await deleteClaim(brandId, claim.id);
                  onChanged();
                }}
              />
            </div>
          </li>
        ))}
      </ul>
      <Pager page={page} pageCount={pageCount} totalCount={totalCount} onChange={goToPage} />
    </section>
  );
}
