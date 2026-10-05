import { useState } from "react";
import { EmptyState } from "@/components/layout/EmptyState";
import {
  confirmProductEconomics,
  CURRENCY_SYMBOLS,
  type AssumptionField,
  type ProductEconomics,
} from "@/lib/productsApi";
import { Badge } from "../shared/Badge";
import { EconomicsPanel } from "../panels/EconomicsPanel";

/** 假設值 chip：黃色小標籤，掛在還在用基準值的欄位旁邊（decision 17／18）。 */
function AssumptionChip({ field, assumptions }: { field: AssumptionField; assumptions: AssumptionField[] }) {
  if (!assumptions.includes(field)) return null;
  return (
    <span className="ml-1 rounded-full bg-warning/15 px-1.5 py-0.5 text-[10px] font-medium text-warning">
      假設
    </span>
  );
}

/** 產品經濟數字分頁（契約 S6.32–S6.35）。 */
export function EconomicsTab({
  brandId,
  productId,
  economics,
  onChanged,
}: {
  brandId: string;
  productId: string;
  economics: ProductEconomics | null;
  onChanged: () => void;
}) {
  const [panelOpen, setPanelOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const symbol = economics ? (CURRENCY_SYMBOLS[economics.currency] ?? economics.currency) : "";

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="font-display text-lg text-foreground">產品經濟數字</h2>
        <button
          type="button"
          onClick={() => setPanelOpen(true)}
          className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90"
        >
          {economics ? "更新數字" : "填寫產品經濟數字"}
        </button>
      </div>

      {economics === null ? (
        <EmptyState
          title="還沒有填產品經濟數字"
          description="填了售價與成本之後，之後才算得出這個產品的 CPA 與 ROAS 標準。"
          actionLabel="填寫產品經濟數字"
          onAction={() => setPanelOpen(true)}
        />
      ) : (
        <div className="flex flex-col gap-3 rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)]">
          <div className="flex items-center gap-2">
            <Badge tone={economics.status === "confirmed" ? "success" : "warning"}>
              {economics.status === "confirmed" ? `已確認・確認人 ${economics.confirmed_by ?? "—"}` : "待確認"}
            </Badge>
          </div>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
            <dt className="text-muted-foreground">售價</dt>
            <dd className="text-foreground">
              {symbol}
              {economics.selling_price}
            </dd>
            <dt className="text-muted-foreground">固定成本</dt>
            <dd className="text-foreground">
              {economics.fixed_cost === null ? "—" : `${symbol}${economics.fixed_cost}`}
            </dd>
            <dt className="text-muted-foreground">單位變動成本</dt>
            <dd className="text-foreground">
              {economics.unit_variable_cost === null ? "—" : `${symbol}${economics.unit_variable_cost}`}
              <AssumptionChip field="cost" assumptions={economics.assumptions} />
            </dd>
            <dt className="text-muted-foreground">運費</dt>
            <dd className="text-foreground">
              {economics.shipping_cost === null ? "—" : `${symbol}${economics.shipping_cost}`}
              <AssumptionChip field="shipping" assumptions={economics.assumptions} />
            </dd>
            <dt className="text-muted-foreground">成交率</dt>
            <dd className="text-foreground">
              {economics.close_rate === null ? "未設定" : `${economics.close_rate}%`}
              <AssumptionChip field="close_rate" assumptions={economics.assumptions} />
            </dd>
            <dt className="text-muted-foreground">幣別</dt>
            <dd className="text-foreground">{economics.currency}</dd>
          </dl>

          {economics.status === "pending" && (
            <div className="flex flex-col gap-2 rounded-md border border-warning/40 bg-warning/5 p-3 text-sm">
              <p className="text-foreground">這筆是 AI 快掃抓到的售價，其他欄位還沒有人填過，確認一下無誤嗎？</p>
              {confirming ? (
                <p className="text-muted-foreground">處理中…</p>
              ) : (
                <div>
                  <button
                    type="button"
                    onClick={async () => {
                      setConfirming(true);
                      await confirmProductEconomics(brandId, productId).catch(() => undefined);
                      setConfirming(false);
                      onChanged();
                    }}
                    className="rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground hover:border-primary hover:text-primary"
                  >
                    確認無誤
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {panelOpen && (
        <EconomicsPanel
          brandId={brandId}
          productId={productId}
          economics={economics}
          onClose={() => setPanelOpen(false)}
          onSaved={() => {
            setPanelOpen(false);
            onChanged();
          }}
        />
      )}
    </div>
  );
}
