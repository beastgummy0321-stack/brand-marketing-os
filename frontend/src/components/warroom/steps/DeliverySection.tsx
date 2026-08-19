import { useEffect, useState } from "react";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { CopyIconButton } from "@/components/workbench/shared/CopyIconButton";
import { confirmDelivery, fetchDelivery, rejectDeliveryItem, type DeliveryActionCard, type DeliveryView } from "@/lib/deliveryApi";

type LoadState = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: DeliveryView };

/** 交貨確認（F2 畫面 3）：只在素材已可交付時露出兩步確認，交接包維持由下方既有區塊處理。 */
export function DeliverySection({ brandId, cycleId }: { brandId: string; cycleId: string }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [facts, setFacts] = useState<string[]>([]);
  const [budgetConfirmed, setBudgetConfirmed] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [rejecting, setRejecting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionCards, setActionCards] = useState<DeliveryActionCard[]>([]);

  function applyView(data: DeliveryView) {
    setState({ status: "ready", data });
    setFacts(data.items.filter((_, index) => data.checks.facts_confirmed[index]).map((item) => item.id));
    setBudgetConfirmed(data.checks.budget_confirmed);
  }

  function load() {
    setState({ status: "loading" });
    fetchDelivery(brandId, cycleId)
      .then(applyView)
      .catch((err: unknown) => setState({ status: "error", message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。" }));
  }

  useEffect(load, [brandId, cycleId]);

  async function reject(itemId: string) {
    setRejecting(itemId);
    setError(null);
    try {
      applyView(await rejectDeliveryItem(brandId, cycleId, itemId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "退回調整失敗，請稍後再試。");
    } finally {
      setRejecting(null);
    }
  }

  async function confirm() {
    setConfirming(true);
    setError(null);
    try {
      const result = await confirmDelivery(brandId, cycleId, facts, budgetConfirmed);
      if (result.status === "failed") {
        setError(result.reason ?? "交接組裝失敗，請稍後再試。");
      } else {
        setActionCards(result.action_cards);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "確認失敗，請稍後再試。");
    } finally {
      setConfirming(false);
    }
  }

  if (state.status === "loading") return <Skeleton className="h-44 w-full" />;
  if (state.status === "error") return <EmptyState title="交貨資料讀取失敗" description={state.message} onAction={load} actionLabel="重新載入" />;

  const { data } = state;
  if (data.status === "assembling") {
    return <div className="rounded-lg border border-border bg-card p-5 text-sm text-muted-foreground">素材還在準備中；完成後會在這裡讓你確認。</div>;
  }
  const factsReady = data.items.length > 0 && data.items.every((item) => facts.includes(item.id));
  const canConfirm = factsReady && budgetConfirmed;
  const missing = [factsReady ? null : "內容打勾", budgetConfirmed ? null : "花費確認"].filter(Boolean).join("、");

  return (
    <section className="flex flex-col gap-4 rounded-lg border border-border bg-card p-5 shadow-[var(--shadow-card)]">
      <div>
        <h2 className="font-display text-lg text-foreground">交貨確認</h2>
        {data.reason && <p className="mt-1 text-sm text-muted-foreground">{data.reason}</p>}
      </div>
      {data.status === "failed" && <p className="rounded-md border border-danger/30 bg-danger/10 p-3 text-sm text-danger">交接組裝失敗；已保留你的勾選，可修正後再送出。</p>}
      {data.items.map((item) => (
        <article key={item.id} className="rounded-md border border-border p-4 text-sm">
          <p className="font-medium text-foreground">{item.copy}</p>
          <p className="mt-2 text-muted-foreground">{item.image_description}</p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <CopyIconButton label="手動生圖（複製描述）" ariaLabel="複製圖片描述" getText={() => item.image_prompt} />
            <button type="button" disabled className="rounded-md border border-border px-3 py-1.5 text-xs text-muted-foreground opacity-50">內建生圖</button>
            <button type="button" disabled={rejecting === item.id} onClick={() => void reject(item.id)} className="ml-auto text-xs font-medium text-danger hover:underline disabled:opacity-50">
              {rejecting === item.id ? "送出中…" : "退回調整"}
            </button>
          </div>
          <label className="mt-3 flex items-center gap-2 text-foreground">
            <input type="checkbox" checked={facts.includes(item.id)} onChange={() => setFacts((current) => current.includes(item.id) ? current.filter((id) => id !== item.id) : [...current, item.id])} />
            這些內容是事實
          </label>
        </article>
      ))}
      <label className="flex items-center gap-2 rounded-md border border-border p-4 text-sm text-foreground">
        <input type="checkbox" checked={budgetConfirmed} onChange={() => setBudgetConfirmed((value) => !value)} />
        這次最多花 NT$ {data.checks.budget_cap.toLocaleString("zh-TW")}
      </label>
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" disabled={!canConfirm || confirming} onClick={() => void confirm()} className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50">
          {confirming ? "送出中…" : data.status === "failed" ? "重新嘗試確認" : "兩步都確認，產出上架行動卡"}
        </button>
        {!canConfirm && <span className="text-sm text-muted-foreground">還缺：{missing}</span>}
      </div>
      {error && <p className="text-sm text-danger">{error}</p>}
      {actionCards.length > 0 && (
        <div className="flex flex-col gap-2 rounded-md bg-success/10 p-4 text-sm text-success">
          <p>上架行動卡已產出，可以接著使用下方交接包。</p>
          {actionCards.map((card) => (
            <article key={card.id} className="rounded-md border border-success/30 bg-card p-3 text-foreground">
              <p className="font-medium">{card.campaign_name}</p>
              <p className="mt-1 text-xs text-muted-foreground">{card.adset_name}／{card.ad_name}｜每日 NT$ {card.daily_budget.toLocaleString("zh-TW")}</p>
              {card.full_url && <p className="mt-1 break-all text-xs text-muted-foreground">{card.full_url}</p>}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
