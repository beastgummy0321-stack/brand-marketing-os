import { useEffect, useState } from "react";
import { Button } from "@/components/layout/ui/button";
import { getMonthlyBudget, type MonthlyBudget } from "@/lib/adsChangeApi";
import { MonthlyBudgetPanel, budgetMoney, currentBudgetMonth } from "../MonthlyBudgetPanel";

type State = { status: "loading" } | { status: "error" } | { status: "ready"; budget: MonthlyBudget };

// 圖例色點跟長條分段同一組 token（design-system §2.1），v7 原型的 `.lg i` 做法。
const SEGMENT_SWATCH: Record<"spend" | "reserved" | "available", string> = {
  spend: "bg-chart-rest",
  reserved: "bg-border",
  available: "bg-primary",
};

function Swatch({ kind }: { kind: keyof typeof SEGMENT_SWATCH }) {
  return <span aria-hidden="true" className={`inline-block size-2 rounded-sm ${SEGMENT_SWATCH[kind]}`} />;
}

/** 三段可用度長條：已花／預留／可用，佔月總額的比例。任一數字未知或總額未知都不假裝算得出
 * 比例——整條顯示一段灰階，數字仍照實印（design-system §7「誠實的空狀態」）。圖例三個色點
 * 跟長條分段同一組顏色，未知態數字雖然沒有真的畫出對應色塊，色點仍標出「這句話對應哪一段」。 */
function BudgetBar({ budget }: { budget: MonthlyBudget }) {
  const { amount, known_spend, ongoing_estimate, available, currency } = budget;
  const legend = (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
      <span className="inline-flex items-center gap-1.5"><Swatch kind="spend" />已花 {budgetMoney(known_spend, currency)}</span>
      <span className="inline-flex items-center gap-1.5"><Swatch kind="reserved" />預留 {budgetMoney(ongoing_estimate, currency)}</span>
      <span className="inline-flex items-center gap-1.5"><Swatch kind="available" />可用 {budgetMoney(available, currency)}</span>
    </div>
  );
  if (amount === null || amount <= 0 || known_spend === null || ongoing_estimate === null || available === null) {
    return (
      <div className="space-y-2">
        <div className="h-2.5 w-full rounded-full bg-muted" aria-hidden="true" />
        {legend}
      </div>
    );
  }
  const pct = (value: number) => Math.max(0, Math.min(100, (value / amount) * 100));
  return (
    <div className="space-y-2">
      <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-muted">
        <div className="bg-chart-rest" style={{ width: `${pct(known_spend)}%` }} />
        <div className="bg-border" style={{ width: `${pct(ongoing_estimate)}%` }} />
        <div className="bg-primary" style={{ width: `${pct(available)}%` }} />
      </div>
      {legend}
    </div>
  );
}

/** 首頁右側月預算卡（F19-I02）：大數字＋分段長條，header／「調整」對齊跟其他卡一致
 * （review repair (g)：用 `.surface-header`/`.surface-body`，不再自己刻 padding）。
 * 「調整」直接切成既有 `MonthlyBudgetPanel`（compact）——編輯邏輯、驗證與保存全部沿用
 * 那支，這裡不重做一份。 */
export function BudgetCard({ brandId }: { brandId: string }) {
  const month = currentBudgetMonth();
  const [state, setState] = useState<State>({ status: "loading" });
  const [reload, setReload] = useState(0);
  const [adjusting, setAdjusting] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading" });
    getMonthlyBudget(brandId, month, controller.signal)
      .then((budget) => { if (!controller.signal.aborted) setState({ status: "ready", budget }); })
      .catch(() => { if (!controller.signal.aborted) setState({ status: "error" }); });
    return () => controller.abort();
  }, [brandId, month, reload]);

  if (adjusting) {
    return (
      <div className="flex flex-col gap-2">
        <Button
          variant="ghost"
          size="sm"
          className="self-start"
          onClick={() => { setAdjusting(false); setReload((v) => v + 1); }}
        >
          ← 收起
        </Button>
        <MonthlyBudgetPanel brandId={brandId} month={month} compact />
      </div>
    );
  }

  return (
    <section className="surface" aria-label="本月可新增承諾">
      <div className="surface-header">
        <div>
          <h2>可新增承諾</h2>
          <p className="text-xs text-muted-foreground">{month}・全品牌</p>
        </div>
        {state.status === "ready" && (
          <Button variant="ghost" size="sm" onClick={() => setAdjusting(true)}>調整</Button>
        )}
      </div>
      <div className="surface-body space-y-3">
        {state.status === "loading" && (
          <p role="status" className="text-sm text-muted-foreground">正在整理月預算…</p>
        )}
        {state.status === "error" && (
          <div className="space-y-2">
            <p role="alert" className="text-sm text-warning">月預算暫時讀取不到。</p>
            <Button variant="outline" size="sm" onClick={() => setReload((v) => v + 1)}>重新讀取月預算</Button>
          </div>
        )}
        {state.status === "ready" && (
          <>
            <p className="numeric flex flex-wrap items-baseline gap-x-1 text-[28px] font-semibold tracking-tight">
              <span className="whitespace-nowrap">{budgetMoney(state.budget.available, state.budget.currency)}</span>
              {state.budget.amount !== null && (
                <span className="whitespace-nowrap text-sm font-normal text-muted-foreground">
                  / {budgetMoney(state.budget.amount, state.budget.currency)}
                </span>
              )}
            </p>
            <BudgetBar budget={state.budget} />
          </>
        )}
      </div>
    </section>
  );
}
