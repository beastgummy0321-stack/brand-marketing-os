import { useEffect, useState, type ReactNode } from "react";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { claimCampaign, fetchClaims, ignoreCampaign, type PendingClaim } from "@/lib/claimsApi";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; items: PendingClaim[] };

export function ClaimsPage({ brandId }: { brandId: string }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [savingId, setSavingId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  function load() {
    setState({ status: "loading" });
    fetchClaims(brandId)
      .then((items) => setState({ status: "ready", items }))
      .catch((error: unknown) => setState({ status: "error", message: error instanceof Error ? error.message : "讀取失敗，請稍後再試。" }));
  }

  useEffect(load, [brandId]);

  async function handleAction(item: PendingClaim, action: "claim" | "ignore") {
    setSavingId(item.id);
    setMessage(null);
    try {
      const result = action === "claim"
        ? await claimCampaign(brandId, item.id)
        : await ignoreCampaign(brandId, item.id);
      setMessage(result.message);
      load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "處理失敗，請稍後再試。");
    } finally {
      setSavingId(null);
    }
  }

  let content: ReactNode;
  if (state.status === "loading") {
    content = <div className="flex flex-col gap-3">{Array.from({ length: 3 }, (_, index) => <Skeleton key={index} className="h-36" />)}</div>;
  } else if (state.status === "error") {
    content = <EmptyState title="讀取失敗" description={state.message} actionLabel="重新載入" onAction={load} />;
  } else if (state.items.length === 0) {
    content = <EmptyState title="沒有待認領的廣告" description="新的廣告活動同步進來時會出現在這裡。" />;
  } else {
    content = (
      <div className="flex flex-col gap-3">
        {state.items.map((item) => {
          const saving = savingId === item.id;
          return (
            <article key={item.id} className="rounded-lg border border-border bg-card p-4 shadow-[var(--shadow-card)]">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <h2 className="text-base font-medium text-foreground">{item.campaign_name || "未命名廣告活動"}</h2>
                {item.is_suggested && <span className="rounded-full border border-primary/40 bg-primary/10 px-2 py-0.5 text-xs text-primary">系統猜是這個品牌的</span>}
              </div>
              <p className="mt-2 text-sm text-muted-foreground">第一次看到 {item.first_seen_at.slice(0, 10)}</p>
              <div className="mt-4 flex flex-wrap gap-2">
                <button type="button" disabled={saving} onClick={() => void handleAction(item, "claim")} className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60">
                  {saving ? "處理中…" : "是，這是這個品牌的"}
                </button>
                <button type="button" disabled={saving} onClick={() => void handleAction(item, "ignore")} className="rounded-md border border-border px-3 py-1.5 text-sm font-medium text-foreground hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-60">
                  不是
                </button>
              </div>
            </article>
          );
        })}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <Breadcrumb items={[{ label: "跨品牌總覽", href: "/" }, { label: "還沒認領的廣告" }]} />
      <div>
        <h1 className="font-display text-2xl text-foreground">還沒認領的廣告</h1>
        <p className="mt-1 text-sm text-muted-foreground">這些廣告活動系統還不確定是不是這個品牌的。認領之後，它的花費與成效才會算進這個品牌。</p>
      </div>
      {message && <p className="rounded-md bg-success/10 px-3 py-2 text-sm text-foreground">{message}</p>}
      {content}
    </div>
  );
}
