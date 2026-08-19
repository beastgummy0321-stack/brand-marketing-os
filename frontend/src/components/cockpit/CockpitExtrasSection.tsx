import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { completeTaskCard, fetchCockpitExtras, type CockpitExtras } from "@/lib/cockpitExtrasApi";

type LoadState = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: CockpitExtras };

const LEGACY_COPY: Record<string, (value: number | boolean) => string> = {
  wisdom: (value) => `累積智慧 ${value} 條`,
  effective_direction: (value) => `有效方向 ${value} 個`,
  prohibition: (value) => `生效禁令 ${value} 條`,
  material_stock: (value) => `素材庫存 ${value} 則`,
  customer_understanding: (value) => value ? "顧客理解已累積" : "顧客理解還在累積",
};

// ponytail: 除素材庫存外，既有路由中以智庫最接近這些長期系統項目。

/** 駕駛艙補肉（F2 畫面 5）：讀品牌層彙總與任務卡，完成動作只寫回既有 task_card。 */
export function CockpitExtrasSection({ brandId }: { brandId: string }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [savingCard, setSavingCard] = useState<string | null>(null);

  function load() {
    setState({ status: "loading" });
    fetchCockpitExtras(brandId).then((data) => setState({ status: "ready", data })).catch((error: unknown) => setState({ status: "error", message: error instanceof Error ? error.message : "讀取失敗，請稍後再試。" }));
  }
  useEffect(load, [brandId]);

  async function markDone(cardId: string) {
    setSavingCard(cardId);
    try {
      const updated = await completeTaskCard(brandId, cardId);
      setState((current) => current.status !== "ready" ? current : { status: "ready", data: { ...current.data, task_cards: current.data.task_cards.map((card) => card.id === cardId ? updated : card) } });
    } finally {
      setSavingCard(null);
    }
  }

  if (state.status === "loading") return <div className="grid grid-cols-2 gap-4"><Skeleton className="h-40" /><Skeleton className="h-40" /></div>;
  if (state.status === "error") return <EmptyState title="補充資料讀取失敗" description={state.message} onAction={load} actionLabel="重新載入" />;

  const { data } = state;
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <section className="rounded-lg border border-border bg-card p-5 shadow-[var(--shadow-card)]"><h2 className="font-display text-lg text-foreground">長期系統</h2><div className="mt-3 grid gap-2">{data.legacy.map((card) => <Link key={card.key} to={card.key === "material_stock" ? `/brands/${brandId}/workbench` : `/brands/${brandId}/library`} className="rounded-md border border-border p-3 text-sm text-foreground hover:border-primary hover:text-primary">{LEGACY_COPY[card.key](card.value)}<span className="ml-2 text-xs text-muted-foreground">去哪看</span></Link>)}</div></section>
        <section className="rounded-lg border border-border bg-card p-5 shadow-[var(--shadow-card)]"><h2 className="font-display text-lg text-foreground">任務卡</h2>{data.task_cards.length === 0 ? <div className="mt-3"><EmptyState title="目前沒有任務卡" description="提案書核可後，這裡會出現要完成的事。" actionHref={`/brands/${brandId}/campaigns`} actionInternal actionLabel="查看檔期" /></div> : <div className="mt-3 flex flex-col gap-2">{data.task_cards.map((card) => <label key={card.id} className={`flex items-center gap-3 rounded-md border border-border p-3 text-sm ${card.done ? "text-muted-foreground line-through" : "text-foreground"}`}><input type="checkbox" checked={card.done} disabled={card.done || savingCard === card.id} onChange={() => void markDone(card.id)} />{card.title}</label>)}</div>}</section>
      </div>
      <section className="rounded-lg border border-border bg-card p-5 shadow-[var(--shadow-card)]"><h2 className="font-display text-lg text-foreground">三件事</h2><div className="mt-3 grid grid-cols-1 gap-3 text-sm sm:grid-cols-3"><p>產品資訊完整度 {data.todo3.product_completeness}%</p><p>好客戶定義 {data.todo3.good_customer_defined ? "已填" : "未填"}</p><p className="text-muted-foreground">回覆速度 之後接</p></div></section>
    </div>
  );
}
