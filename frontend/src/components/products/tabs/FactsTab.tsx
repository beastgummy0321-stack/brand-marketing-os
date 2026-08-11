import { useState } from "react";
import { EmptyState } from "@/components/layout/EmptyState";
import { Pager } from "@/components/layout/Pager";
import { deleteProductFact, type ProductFact, type ResearchJobState } from "@/lib/productsApi";
import { usePagination } from "@/lib/usePagination";
import { Badge } from "../shared/Badge";
import { InlineDeleteButton } from "../shared/InlineDeleteButton";
import { ResearchProgressRow } from "../shared/ResearchProgressRow";
import { FactConfirmPanel } from "../panels/FactConfirmPanel";
import { FactPanel } from "../panels/FactPanel";

type PanelState =
  | { mode: "closed" }
  | { mode: "new" }
  | { mode: "edit"; fact: ProductFact }
  | { mode: "confirm"; fact: ProductFact };

/** 產品事實分頁（契約 S6.22–S6.31）：已確認／待確認兩段，頂端可能疊一條背景調研進行中／
 * 失敗列（`job` 由詳情頁統一輪詢後往下傳，見 `ProductDetailPage.tsx`——調研觸發鈕在總覽
 * 區塊、不在這個分頁裡，狀態要能跨分頁存活，所以輪詢邏輯提到父層，這裡只負責顯示）。
 * 各段超過 12 列分頁（互動鐵則⑥）。 */
export function FactsTab({
  brandId,
  productId,
  facts,
  job,
  onDismissFailedJob,
  onChanged,
}: {
  brandId: string;
  productId: string;
  facts: ProductFact[];
  job: ResearchJobState | null;
  onDismissFailedJob: () => void;
  onChanged: () => void;
}) {
  const [panel, setPanel] = useState<PanelState>({ mode: "closed" });
  const confirmed = facts.filter((f) => f.status === "confirmed");
  const pending = facts.filter((f) => f.status === "pending");
  const confirmedPage = usePagination(confirmed);
  const pendingPage = usePagination(pending);

  return (
    <div className="flex flex-col gap-6">
      {job && <ResearchProgressRow job={job} onDismissFailed={onDismissFailedJob} />}

      <div className="flex items-center justify-between">
        <h2 className="font-display text-lg text-foreground">產品事實</h2>
        <button
          type="button"
          onClick={() => setPanel({ mode: "new" })}
          className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90"
        >
          新增產品事實
        </button>
      </div>

      <section ref={confirmedPage.topRef} className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold text-foreground">已確認（{confirmed.length}）</h3>
        {confirmed.length === 0 ? (
          <EmptyState
            title="這個產品還沒有已確認的產品事實"
            description="產品事實包含核心資訊、機制與差異化、使用情境。優惠與活動價不屬於這裡。"
          />
        ) : (
          <>
            <ul className="flex flex-col gap-2">
              {confirmedPage.pageItems.map((fact) => (
                <FactCard
                  key={fact.id}
                  fact={fact}
                  brandId={brandId}
                  productId={productId}
                  onEdit={() => setPanel({ mode: "edit", fact })}
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
                productId={productId}
                onEdit={() => setPanel({ mode: "edit", fact })}
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
          productId={productId}
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
          productId={productId}
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
          productId={productId}
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
  productId,
  onEdit,
  onConfirm,
  onChanged,
}: {
  fact: ProductFact;
  brandId: string;
  productId: string;
  onEdit: () => void;
  onConfirm?: () => void;
  onChanged: () => void;
}) {
  return (
    <li className="flex flex-col gap-2 rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)]">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <Badge>{fact.fact_type_label}</Badge>
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
            confirmText={`確定要刪除「${fact.label}」？刪除後會記在稽核紀錄，但資料本身會消失。`}
            onDelete={async () => {
              await deleteProductFact(brandId, productId, fact.id);
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
