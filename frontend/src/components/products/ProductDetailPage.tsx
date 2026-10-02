import { useEffect, useRef, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { PageHeader } from "@/components/layout/PageHeader";
import { PageTabs } from "@/components/layout/PageTabs";
import { Skeleton } from "@/components/layout/Skeleton";
import {
  archiveProduct,
  confirmProductEconomics,
  COST_PRODUCT_SCAN,
  fetchProductDetail,
  fetchResearchStatus,
  startRescan,
  type ProductDetailBundle,
  type ResearchJobState,
} from "@/lib/productsApi";
import { Badge } from "./shared/Badge";
import { ClaimsTab } from "./tabs/ClaimsTab";
import { EconomicsTab } from "./tabs/EconomicsTab";
import { FactsTab } from "./tabs/FactsTab";
import { RulesTab } from "./tabs/RulesTab";
import { HandoffPanel } from "./panels/HandoffPanel";
import { ProductDeletePanel } from "./panels/ProductDeletePanel";

type TabKey = "facts" | "economics-view" | "rules" | "claims";
const NOT_FOUND_MESSAGE = "找不到這筆資料。";
const RESCAN_URL_MISSING = "先填要調研的商品頁網址（從 https:// 開始），AI 才知道要讀哪一頁。";

/** F47-I03 (drill-10 乙 #6): the green line after a pasted-back reply. A reply that yields nothing is
 * refused by the server (the panel stays open with the reason and the pasted text), so 0 here means
 * every fact it carried is already on the list. */
function handoffDoneMessage(addedCount: number): string {
  return addedCount > 0
    ? `深研交接包貼回完成，新增了 ${addedCount} 條待確認事實。`
    : "貼回的事實都已經在清單裡，這次沒有新增。";
}

type LoadState =
  | { status: "loading" }
  | { status: "not-found" }
  | { status: "error"; message: string }
  | { status: "ready"; data: ProductDetailBundle };

/** 產品詳情（契約 S6.15–S6.56，票 B2-products）：頭部總覽＋四張分頁卡，合併舊版
 * `product_hub.html` 選單頁與四個子頁。背景調研（新建與再次調研共用）在這裡統一輪詢——
 * 觸發鈕在總覽區塊、進度列顯示在事實分頁，狀態要跨分頁存活，見 `FactsTab.tsx` 開頭註解。 */
export function ProductDetailPage({ brandId, productId }: { brandId: string; productId: string }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [searchParams, setSearchParams] = useSearchParams();
  const [rescanUrl, setRescanUrl] = useState("");
  const [rescanError, setRescanError] = useState<string | null>(null);
  const [job, setJob] = useState<ResearchJobState | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // setInterval 綁的是掛載當下那個 checkJob，閉包裡的 state 永遠是舊的——用 ref 記「剛剛
  // 是不是正在跑」，不能靠檢查 `job` state（那樣「跑完轉完成」永遠偵測不到，是死結）。
  const hadActiveJobRef = useRef(false);
  const [handoffOpen, setHandoffOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);

  function load() {
    setState({ status: "loading" });
    fetchProductDetail(brandId, productId)
      .then((data) => {
        setState({ status: "ready", data });
        setRescanUrl(data.latest_source_url ?? "");
      })
      .catch((err: unknown) => {
        const message = err instanceof Error ? err.message : "讀取失敗，請稍後再試。";
        setState(message === NOT_FOUND_MESSAGE ? { status: "not-found" } : { status: "error", message });
      });
  }

  useEffect(load, [brandId, productId]);

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  function checkJob() {
    fetchResearchStatus(brandId, productId)
      .then((j) => {
        if (j.status === "running" || j.status === "waiting") {
          hadActiveJobRef.current = true;
          setJob(j);
        } else if (j.status === "failed") {
          hadActiveJobRef.current = true;
          setJob(j);
          stopPolling();
        } else {
          stopPolling();
          setJob(null);
          if (hadActiveJobRef.current) {
            hadActiveJobRef.current = false;
            load(); // 剛從進行中轉完成：刷新事實清單。
          }
        }
      })
      .catch(() => undefined);
  }

  useEffect(() => {
    checkJob();
    pollRef.current = setInterval(checkJob, 2000);
    return stopPolling;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brandId, productId]);

  const requestedTab = searchParams.get("tab");
  const activeTab: TabKey = (["facts", "economics-view", "rules", "claims"] as TabKey[]).includes(
    requestedTab as TabKey,
  )
    ? (requestedTab as TabKey)
    : "facts";

  function setTab(key: TabKey) {
    const next = new URLSearchParams(searchParams);
    next.set("tab", key);
    setSearchParams(next);
  }

  async function submitRescan() {
    const trimmed = rescanUrl.trim();
    if (!trimmed) {
      // F47-I03 (drill-10 乙 #7): an empty URL used to do nothing visible; say what is missing.
      setRescanError(RESCAN_URL_MISSING);
      return;
    }
    if (!/^https:\/\//.test(trimmed)) {
      setRescanError("這個網址看起來不完整，記得從 https:// 開始，例如「https://example.com/products/xxx」。");
      return;
    }
    setRescanError(null);
    try {
      await startRescan(brandId, productId, trimmed);
      hadActiveJobRef.current = true;
      setJob({
        status: "running",
        stage: "讀取網址中",
        started_at: new Date().toISOString(),
        usual_range_text: "30 到 60 秒",
        error: null,
        added_count: null,
        price_created: false,
      });
      if (!pollRef.current) pollRef.current = setInterval(checkJob, 2000);
      setTab("facts");
    } catch (err) {
      setRescanError(err instanceof Error ? err.message : "送出失敗，請稍後再試。");
    }
  }

  let content: ReactNode;
  if (state.status === "loading") {
    content = (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-24 w-full" />
        <div className="grid grid-cols-4 gap-3">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
        <Skeleton className="h-40 w-full" />
      </div>
    );
  } else if (state.status === "not-found") {
    content = (
      <EmptyState
        title="找不到這個產品"
        description="這個產品可能已經被刪除，或連結不正確。"
        actionHref={`/brands/${brandId}/products`}
        actionLabel="回產品清單"
        actionInternal
      />
    );
  } else if (state.status === "error") {
    content = <EmptyState title="讀取失敗" description={state.message} onAction={load} actionLabel="重新載入" />;
  } else {
    const { data } = state;
    content = (
      <div className="flex flex-col gap-5">
        <div className="flex flex-col gap-4 rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)]">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-2">
              <Badge tone={data.status === "archived" ? "neutral" : "success"}>
                {data.status === "archived" ? "已封存" : "使用中"}
              </Badge>
              <span className="text-xs text-muted-foreground">第 {data.knowledge_version} 版</span>
            </div>
            <button
              type="button"
              onClick={async () => {
                await archiveProduct(brandId, productId);
                load();
              }}
              className="rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground hover:border-primary hover:text-primary"
            >
              {data.status === "archived" ? "恢復使用" : "封存"}
            </button>
          </div>

          {banner && <p className="rounded-md bg-success/10 px-3 py-2 text-sm text-success">{banner}</p>}

          {data.economics_pending && (
            <div className="flex items-center justify-between gap-3 rounded-md border border-warning/40 bg-warning/5 p-3 text-sm">
              <span className="text-foreground">產品經濟數字還是 AI 快掃抓到的售價，確認一下無誤嗎？</span>
              <button
                type="button"
                onClick={async () => {
                  await confirmProductEconomics(brandId, productId);
                  load();
                }}
                className="shrink-0 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground hover:border-primary hover:text-primary"
              >
                確認無誤
              </button>
            </div>
          )}

          <details className="border-t border-border pt-2">
            <summary className="text-sm font-medium text-primary">調研工具 · 再次調研與深入調研</summary>
            <div className="flex flex-wrap items-center gap-2">
              <input
                type="text"
                value={rescanUrl}
                onChange={(e) => {
                  setRescanUrl(e.target.value);
                  setRescanError(null);
                }}
                aria-label="再次調研網址"
                placeholder="https://example.com/products/xxx"
                className="min-w-[16rem] flex-1 rounded-md border border-border px-3 py-1.5 text-sm text-foreground"
              />
              <button
                type="button"
                disabled={job?.status === "running" || job?.status === "waiting"}
                onClick={() => void submitRescan()}
                className="rounded-md border border-primary px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {job?.status === "running" || job?.status === "waiting"
                  ? "調研進行中…"
                  : `AI 再次調研（預估 US$${COST_PRODUCT_SCAN.toFixed(2)}）`}
              </button>
              <button
                type="button"
                onClick={() => setHandoffOpen(true)}
                className="text-xs text-primary hover:underline"
              >
                深入調研 →
              </button>
            </div>
            {rescanError && <p role="alert" className="text-sm text-danger">{rescanError}</p>}
          </details>
        </div>

        <PageTabs value={activeTab} onChange={setTab} items={data.cards.map(card => ({value:card.key,label:card.pending > 0 ? `${card.title} · 待確認 ${card.pending}` : card.title,count:card.count}))}/>

        {activeTab === "facts" && (
          <FactsTab
            brandId={brandId}
            productId={productId}
            facts={data.facts}
            job={job}
            onDismissFailedJob={() => setJob(null)}
            onChanged={load}
          />
        )}
        {activeTab === "economics-view" && (
          <EconomicsTab brandId={brandId} productId={productId} economics={data.economics} onChanged={load} />
        )}
        {activeTab === "rules" && <RulesTab brandId={brandId} productId={productId} rules={data.rules} />}
        {activeTab === "claims" && <ClaimsTab brandId={brandId} productId={productId} claims={data.claims} />}

        {data.status === "archived" && (
          <div className="flex flex-col gap-2 rounded-md border border-danger/40 bg-danger/5 p-4">
            <h3 className="font-display text-base text-foreground">永久刪除產品</h3>
            <p className="text-sm text-muted-foreground">已封存的產品可以永久刪除，這個動作不能復原。</p>
            <div>
              <button
                type="button"
                onClick={() => setDeleteOpen(true)}
                className="rounded-md border border-danger px-4 py-2 text-sm font-medium text-danger hover:bg-danger/10"
              >
                永久刪除這個產品…
              </button>
            </div>
          </div>
        )}

        {handoffOpen && (
          <HandoffPanel
            brandId={brandId}
            productId={productId}
            onClose={() => setHandoffOpen(false)}
            onSaved={(addedCount) => {
              setHandoffOpen(false);
              setBanner(handoffDoneMessage(addedCount));
              load();
            }}
          />
        )}
        {deleteOpen && (
          <ProductDeletePanel
            brandId={brandId}
            productId={productId}
            productName={data.name}
            onClose={() => setDeleteOpen(false)}
            onDeleted={() => {
              window.location.href = `/app/brands/${brandId}/products`;
            }}
          />
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <Breadcrumb
        items={[
          { label: "跨品牌總覽", href: "/" },
          { label: "產品", href: `/brands/${brandId}/products` },
          { label: state.status === "ready" ? state.data.name : "產品詳情" },
        ]}
      />
      <PageHeader title={state.status === "ready" ? state.data.name : "產品詳情"} description="產品知識、經濟數字與宣稱依據"/>
      {content}
    </div>
  );
}
