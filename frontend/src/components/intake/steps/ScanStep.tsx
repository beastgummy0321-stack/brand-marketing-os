import { useState } from "react";
import type { IntakeDraft } from "@/lib/intakeApi";
import { createScannedProducts, fetchScanStatus, skipRemainingAi, skipScan, startScan } from "@/lib/intakeApi";
import { Badge } from "../shared/Badge";
import { IntakeJobRow } from "../shared/IntakeJobRow";
import { LimitCard } from "../shared/LimitCard";
import { useIntakeJob } from "../useIntakeJob";

/** 初掃＋初掃結果（契約 S4.14–S4.24）：進入這一步且草稿還沒掃過就自動開始背景工作。 */
export function ScanStep({
  brandId,
  draft,
  onRefresh,
  onNext,
}: {
  brandId: string;
  draft: IntakeDraft;
  onRefresh: () => void;
  onNext: () => void;
}) {
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createdMsg, setCreatedMsg] = useState<string | null>(null);
  const { job, limitBlock, raising, retry, raise } = useIntakeJob(
    brandId,
    "scan",
    !draft.scan_done,
    () => startScan(brandId),
    () => fetchScanStatus(brandId),
    onRefresh,
  );

  async function handleSkip() {
    await skipScan(brandId);
    onRefresh();
  }

  async function handleSkipRemaining() {
    await skipRemainingAi(brandId);
    onRefresh();
  }

  async function handleCreateProducts(names: string[]) {
    setCreating(true);
    try {
      const res = await createScannedProducts(brandId, names);
      setCreatedMsg(`已建立 ${res.created_count} 個產品。`);
      onRefresh();
    } finally {
      setCreating(false);
    }
  }

  if (limitBlock) {
    return <LimitCard block={limitBlock} raising={raising} onRaise={() => void raise()} onSkipRemaining={() => void handleSkipRemaining()} />;
  }

  if (!draft.scan_done) {
    if (!job) return <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">準備開始初掃…</div>;
    return (
      <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-6 shadow-[var(--shadow-card)]">
        <IntakeJobRow
          job={job}
          runningLabel="AI 正在初掃"
          actions={[
            { label: "再試一次（預估 US$0.30）", onClick: () => void retry() },
            { label: "跳過這一步", onClick: () => void handleSkip() },
            { label: "前往設定頁", onClick: () => window.location.assign("/app/settings") },
          ]}
        />
      </div>
    );
  }

  const impressions = draft.scan_impressions;
  const scannedProducts = [...new Set(draft.scan_products)];

  return (
    <div className="flex flex-col gap-5 rounded-lg border border-border bg-card p-6 shadow-[var(--shadow-card)]">
      <div>
        <h2 className="font-display text-lg text-foreground">我先讀過一遍了</h2>
        <p className="text-sm text-muted-foreground">這還不是事實，只是讓我知道接下來要問你什麼。</p>
      </div>

      {impressions.length === 0 ? (
        <div className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
          這次沒有讀到可用的內容。你給的網址都讀不到，或內容太少。可以直接跳過初掃，用問答把重點講給我聽。
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {impressions.map((imp, i) => (
            <div key={i} className="flex flex-col gap-1 rounded-md border border-border p-3 text-sm">
              <Badge>看起來像 {imp.looks_like}</Badge>
              <p className="font-medium text-foreground">{imp.title}</p>
              <p className="text-muted-foreground">{imp.content}</p>
              <p className="text-xs text-muted-foreground">依據：{imp.basis}</p>
            </div>
          ))}
        </div>
      )}

      {scannedProducts.length > 0 && (
        <div className="flex flex-col gap-2 rounded-md border border-border p-3">
          <p className="text-sm font-medium text-foreground">我在資料裡看到這些產品</p>
          <ScanProductChecklist
            products={scannedProducts}
            created={draft.created_product_names}
            creating={creating}
            onCreate={(names) => void handleCreateProducts(names)}
          />
          {createdMsg && <p className="text-xs text-success">{createdMsg}</p>}
        </div>
      )}

      {draft.url_results.length > 0 && (
        <div className="flex flex-col gap-2 text-sm">
          <button type="button" onClick={() => setDetailsOpen((v) => !v)} className="self-start font-medium text-primary hover:underline">
            {detailsOpen ? "收起「這次讀了哪些東西」" : "這次讀了哪些東西"}
          </button>
          {detailsOpen && (
            <ul className="flex flex-col gap-1 text-xs text-muted-foreground">
              {draft.url_results.map((r, i) => (
                <li key={i} className="break-all">
                  {r.ok ? <Badge tone="success">成功</Badge> : <Badge tone="danger">失敗</Badge>} {r.url}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <button
        type="button"
        onClick={onNext}
        className="self-start rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
      >
        開始回答問題
      </button>
    </div>
  );
}

function ScanProductChecklist({
  products,
  created,
  creating,
  onCreate,
}: {
  products: string[];
  created: string[];
  creating: boolean;
  onCreate: (names: string[]) => void;
}) {
  const [checked, setChecked] = useState<Set<string>>(new Set(products));

  return (
    <div className="flex flex-col gap-2">
      <ul className="flex flex-col gap-1 text-sm">
        {products.map((name) => {
          const isCreated = created.includes(name);
          return (
            <li key={name} className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={isCreated || checked.has(name)}
                disabled={isCreated}
                onChange={(e) =>
                  setChecked((prev) => {
                    const next = new Set(prev);
                    if (e.target.checked) next.add(name);
                    else next.delete(name);
                    return next;
                  })
                }
              />
              <span className="text-foreground">{name}</span>
              {isCreated && <Badge tone="success">已建立</Badge>}
            </li>
          );
        })}
      </ul>
      <button
        type="button"
        disabled={creating || products.every((p) => created.includes(p))}
        onClick={() => onCreate(products.filter((p) => checked.has(p) && !created.includes(p)))}
        className="self-start rounded-md border border-primary px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {creating ? "處理中…" : "建立勾選的產品"}
      </button>
    </div>
  );
}
