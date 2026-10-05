import { Link } from "react-router-dom";
import { TriangleAlert } from "lucide-react";
import { EmptyState } from "@/components/layout/EmptyState";
import type { ClaimType, ProductClaim } from "@/lib/productsApi";

const GROUPS: { type: ClaimType; title: string }[] = [
  { type: "approved", title: "可用" },
  { type: "high_risk", title: "高風險" },
  { type: "forbidden", title: "禁用" },
];

/** 適用宣稱分頁（唯讀，契約 S6.38–S6.39）：三段分類，品牌層宣稱只能到品牌智庫（S5）改。 */
export function ClaimsTab({
  brandId,
  productId,
  claims,
}: {
  brandId: string;
  productId: string;
  claims: ProductClaim[];
}) {
  return (
    <div className="flex flex-col gap-6">
      <h2 className="font-display text-lg text-foreground">適用宣稱</h2>

      {claims.length === 0 ? (
        <EmptyState
          title="這個產品沒有專屬的宣稱"
          description="品牌層的宣稱仍然適用。"
          actionHref={`/brands/${brandId}/library?tab=claims`}
          actionLabel="到品牌智庫新增"

        />
      ) : (
        GROUPS.map(({ type, title }) => {
          const group = claims.filter((c) => c.claim_type === type);
          if (group.length === 0) return null;
          return (
            <section key={type} className="flex flex-col gap-2">
              <h3 className="text-sm font-semibold text-foreground">
                {title}（{group.length}）
              </h3>
              <ul className="flex flex-col gap-2">
                {group.map((claim) => (
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
                      {type === "approved" &&
                        (claim.evidence_source_reference
                          ? `佐證：${claim.evidence_source_reference}`
                          : "尚未填寫佐證來源")}
                      {claim.product_id === productId ? (
                        <span>本產品專屬</span>
                      ) : (
                        <>
                          <span aria-hidden="true">・</span>
                          <span>來自品牌設定</span>
                          <span aria-hidden="true">・</span>
                          <Link to={`/brands/${brandId}/library?tab=claims`} className="text-primary hover:underline">
                            到品牌智庫修改
                          </Link>
                        </>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          );
        })
      )}
    </div>
  );
}
