import { useEffect, useState, type ReactNode } from "react";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { formatCurrency } from "@/lib/format";
import { fetchProductList, type ProductListItem } from "@/lib/productsApi";
import {
  createSchedulePlan,
  fetchSchedule,
  type ScheduleState,
} from "@/lib/scheduleApi";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; products: ProductListItem[]; schedule: ScheduleState };

/** 檔期規劃（票 07：最薄路徑）。選產品、確認、送出，畫面下方長出一張方案卡——同一頁，
 * 不換路由、不開 modal（settled 段「Frontend」）。 */
export function SchedulePage({ brandId }: { brandId: string }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [confirming, setConfirming] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  function load() {
    setState({ status: "loading" });
    Promise.all([fetchProductList(brandId), fetchSchedule(brandId)])
      .then(([products, schedule]) => setState({ status: "ready", products, schedule }))
      .catch((err: unknown) =>
        setState({
          status: "error",
          message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。",
        }),
      );
  }

  useEffect(load, [brandId]);

  function toggleProduct(id: string) {
    setSelectedIds((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]));
  }

  async function handleStart() {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const schedule = await createSchedulePlan(brandId, selectedIds);
      setState((prev) => (prev.status === "ready" ? { ...prev, schedule } : prev));
      setConfirming(false);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "排程失敗，請稍後再試。");
    } finally {
      setSubmitting(false);
    }
  }

  let content: ReactNode;
  if (state.status === "loading") {
    content = (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 3 }, (_, i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
    );
  } else if (state.status === "error") {
    content = <EmptyState title="讀取失敗" description={state.message} onAction={load} actionLabel="重新載入" />;
  } else {
    const activeProducts = state.products.filter((p) => p.status === "active");
    const selectedNames = activeProducts
      .filter((p) => selectedIds.includes(p.id))
      .map((p) => p.name);

    content = (
      <div className="flex flex-col gap-4">
        <div className="rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)]">
          <h2 className="mb-1 font-display text-lg text-foreground">這期要投放哪些產品</h2>
          <p className="mb-3 text-sm text-muted-foreground">
            本期每日預算：{formatCurrency(state.schedule.daily_budget)}
            {state.schedule.daily_budget <= 0 && "（尚未設定，請先到設定頁填「檔期日預算」）"}
          </p>
          {activeProducts.length === 0 ? (
            <p className="text-sm text-muted-foreground">這個品牌底下還沒有產品，請先去產品頁新增。</p>
          ) : (
            <div className="flex flex-col gap-2">
              {activeProducts.map((product) => (
                <label key={product.id} className="flex items-center gap-2 text-sm text-foreground">
                  <input
                    type="checkbox"
                    checked={selectedIds.includes(product.id)}
                    onChange={() => toggleProduct(product.id)}
                  />
                  {product.name}
                </label>
              ))}
            </div>
          )}
          <button
            type="button"
            onClick={() => setConfirming(true)}
            disabled={selectedIds.length === 0}
            className="mt-3 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
          >
            確認
          </button>
        </div>

        {confirming && (
          <div className="rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)]">
            <h2 className="mb-1 font-display text-lg text-foreground">確認這期要排程的產品</h2>
            <p className="mb-3 text-sm text-foreground">{selectedNames.join("、")}</p>
            {submitError && <p className="mb-3 text-sm text-danger">{submitError}</p>}
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setConfirming(false)}
                disabled={submitting}
                className="rounded-md border border-border px-3 py-1.5 text-sm font-medium text-foreground hover:bg-muted disabled:cursor-not-allowed disabled:opacity-60"
              >
                修改
              </button>
              <button
                type="button"
                onClick={handleStart}
                disabled={submitting}
                className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {submitting ? "排程中…" : "開始排程"}
              </button>
            </div>
          </div>
        )}

        {state.schedule.plan && <PlanCard plan={state.schedule.plan} />}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <Breadcrumb items={[{ label: "跨品牌總覽", href: "/" }, { label: "檔期" }]} />
      <h1 className="font-display text-2xl text-foreground">檔期</h1>
      {content}
    </div>
  );
}

function PlanCard({ plan }: { plan: NonNullable<ScheduleState["plan"]> }) {
  if (plan.failure) {
    return (
      <div className="rounded-md border border-danger/40 bg-card p-4 shadow-[var(--shadow-card)]">
        <h2 className="mb-1 font-display text-lg text-foreground">方案</h2>
        <p className="text-sm text-danger">{plan.failure}</p>
      </div>
    );
  }

  return (
    <div className="rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)]">
      <h2 className="mb-2 font-display text-lg text-foreground">方案</h2>
      <p className="mb-3 whitespace-pre-wrap text-sm text-foreground">{plan.narrative}</p>
      {plan.splits.length > 0 && (
        <div className="overflow-x-auto rounded-md border border-border">
          <table className="w-full text-left text-sm">
            <thead className="bg-muted text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">方向</th>
                <th className="px-3 py-2 font-medium">比例</th>
                <th className="px-3 py-2 font-medium">每日金額</th>
                <th className="px-3 py-2 font-medium">理由</th>
              </tr>
            </thead>
            <tbody>
              {plan.splits.map((split, i) => (
                <tr key={i} className="border-t border-border">
                  <td className="px-3 py-2 text-foreground">{split.label}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-foreground">
                    {(split.share * 100).toFixed(0)}%
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-foreground">
                    {formatCurrency(split.daily_amount)}
                  </td>
                  <td className="px-3 py-2 text-foreground">{split.why}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
