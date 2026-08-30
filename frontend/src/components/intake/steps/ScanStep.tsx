import { useEffect, useState } from "react";
import { ImageOff } from "lucide-react";
import type { IntakeDraft, ProductCardDraft } from "@/lib/intakeApi";
import { useAuthedImage } from "@/lib/useAuthedImage";
import {
  createProductFromCard,
  createScannedProducts,
  fetchScanStatus,
  retryPhotoProduct,
  skipPhotoProduct,
  skipRemainingAi,
  skipScan,
  startScan,
} from "@/lib/intakeApi";
import { Badge } from "../shared/Badge";
import { IntakeJobRow } from "../shared/IntakeJobRow";
import { LimitCard } from "../shared/LimitCard";
import { useIntakeJob } from "../useIntakeJob";
import { ProductNewPanel } from "../../products/panels/ProductNewPanel";

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
  const [manualOpen, setManualOpen] = useState(false);
  const [retryingToken, setRetryingToken] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
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
    setActionError(null);
    try {
      const res = await createScannedProducts(brandId, names);
      setCreatedMsg(`已建立 ${res.created_count} 個產品。`);
      onRefresh();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "建立產品失敗，請再試一次。");
    } finally {
      setCreating(false);
    }
  }

  async function handleCreateCard(card: ProductCardDraft) {
    setCreating(true);
    setActionError(null);
    try {
      const res = await createProductFromCard(brandId, card.source_photo_token);
      if (!res.product_id) throw new Error("這張產品卡現在還不能建立，請重新讀一次照片。");
      setCreatedMsg(`「${card.name}」已建立為產品。`);
      onRefresh();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "建立產品失敗，請再試一次。");
    } finally {
      setCreating(false);
    }
  }

  async function handleRetryCard(card: ProductCardDraft) {
    setRetryingToken(card.source_photo_token);
    setActionError(null);
    try {
      await retryPhotoProduct(brandId, card.source_photo_token);
      onRefresh();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "這張照片暫時讀不到，請再試一次。");
    } finally {
      setRetryingToken(null);
    }
  }

  async function handleSkipCard(card: ProductCardDraft) {
    setActionError(null);
    try {
      await skipPhotoProduct(brandId, card.source_photo_token);
      onRefresh();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "這張照片暫時略過失敗，請再試一次。");
    }
  }

  useEffect(() => {
    if (!createdMsg) return;
    const timer = window.setTimeout(() => setCreatedMsg(null), 3000);
    return () => window.clearTimeout(timer);
  }, [createdMsg]);

  if (limitBlock) {
    return <LimitCard block={limitBlock} raising={raising} onRaise={() => void raise()} onSkipRemaining={() => void handleSkipRemaining()} />;
  }

  if (!draft.scan_done) {
    if (!job) return <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">準備開始初掃…</div>;
    return (
      <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-6 shadow-[var(--shadow-card)]">
        {job.status !== "failed" && draft.photos.length > 0 ? (
          <div className="flex items-center gap-2 rounded-md border border-dashed border-border bg-muted/40 p-3 text-sm text-muted-foreground">
            <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-primary" aria-hidden="true" />
            正在看你的照片…（{job.stage || "準備中"}）
          </div>
        ) : (
          <IntakeJobRow
            job={job}
            runningLabel="AI 正在初掃"
            actions={[
              { label: "再試一次（預估 US$0.30）", onClick: () => void retry() },
              { label: "跳過這一步", onClick: () => void handleSkip() },
              { label: "前往設定頁", onClick: () => window.location.assign("/app/settings") },
            ]}
          />
        )}
      </div>
    );
  }

  const impressions = draft.scan_impressions;
  const scannedProducts = [...new Set(draft.scan_products)];
  const showProductDrafts = draft.photos.length > 0 || draft.urls.some((url) => url.trim());

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

      {showProductDrafts && (
        <div className="flex flex-col gap-2 rounded-md border border-border p-3">
          <div>
            <p className="text-sm font-medium text-foreground">產品卡草稿</p>
            <p className="text-xs text-muted-foreground">我從你的照片和網址讀出來的；價格看不出來時，問答會再問你。</p>
          </div>
          {draft.product_card_drafts.length > 0 ? (
            <div className="flex flex-col gap-2">
              {draft.product_card_drafts.map((card) => (
                <PhotoProductCard
                  key={card.source_photo_token}
                  brandId={brandId}
                  card={card}
                  photoName={draft.photos.find((photo) => photo.token === card.source_photo_token)?.name}
                  created={draft.created_product_names.includes(card.name)}
                  creating={creating}
                  retrying={retryingToken === card.source_photo_token}
                  onCreate={() => void handleCreateCard(card)}
                  onRetry={() => void handleRetryCard(card)}
                  onSkip={() => void handleSkipCard(card)}
                  onManual={() => setManualOpen(true)}
                />
              ))}
            </div>
          ) : (
            <p className="rounded-md border border-dashed border-border p-3 text-sm text-muted-foreground">
              這次沒有讀出可建立的產品；你仍可照原本流程往下回答問題。
            </p>
          )}

          {scannedProducts.length > 0 && (
            <ScanProductChecklist
              products={scannedProducts}
              created={draft.created_product_names}
              creating={creating}
              onCreate={(names) => void handleCreateProducts(names)}
            />
          )}
        </div>
      )}

      {actionError && <p role="alert" className="text-sm text-danger">{actionError}</p>}

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

      {manualOpen && (
        <ProductNewPanel
          brandId={brandId}
          onClose={() => setManualOpen(false)}
          onCreated={() => {
            setManualOpen(false);
            setCreatedMsg("已建立產品，可以繼續建檔。");
            onRefresh();
          }}
        />
      )}
      {createdMsg && (
        <p role="status" aria-live="polite" className="fixed bottom-5 left-1/2 z-50 -translate-x-1/2 rounded-md bg-foreground px-4 py-2 text-sm text-background shadow-[var(--shadow-card)]">
          {createdMsg}
        </p>
      )}
    </div>
  );
}

function PhotoProductCard({
  brandId,
  card,
  photoName,
  created,
  creating,
  retrying,
  onCreate,
  onRetry,
  onSkip,
  onManual,
}: {
  brandId: string;
  card: ProductCardDraft;
  photoName: string | undefined;
  created: boolean;
  creating: boolean;
  retrying: boolean;
  onCreate: () => void;
  onRetry: () => void;
  onSkip: () => void;
  onManual: () => void;
}) {
  if (card.status === "skipped") {
    return <div className="rounded-md border border-dashed border-border p-3 text-sm text-muted-foreground">這張照片已略過，不會擋住後面的流程。</div>;
  }

  return (
    <div className="flex items-start gap-3 rounded-md border border-border p-3 text-sm">
      <PhotoThumbnail brandId={brandId} photoName={photoName} />
      <div className="min-w-0 flex-1 space-y-1">
        {card.status === "ready" ? (
          <>
            <p className="font-medium text-foreground">{card.name}</p>
            {card.specification && <p className="text-muted-foreground">規格：{card.specification}</p>}
            {card.selling_points.length > 0 && <p className="text-muted-foreground">賣點：{card.selling_points.join("、")}</p>}
            {card.gaps.map((gap) => (
              <Badge key={gap} tone="warning">{gap === "價格" ? "💰 價格看不出來——問答時會問你" : `${gap}還不清楚——問答時會問你`}</Badge>
            ))}
          </>
        ) : card.status === "unreadable" ? (
          <>
            <p className="font-medium text-foreground">這張我讀不出產品資訊</p>
            <p className="text-muted-foreground">{card.message ?? "可以自己填，或略過這張照片。"}</p>
          </>
        ) : (
          <>
            <p className="font-medium text-danger">這張照片暫時讀不到</p>
            <p className="text-muted-foreground">{card.message ?? "不是你的問題，可以再試一次。"}</p>
          </>
        )}
      </div>
      <div className="flex shrink-0 flex-col items-end gap-2">
        {card.status === "ready" ? (
          <button
            type="button"
            disabled={created || creating}
            onClick={onCreate}
            className="rounded-md border border-primary px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {created ? "已建立" : creating ? "建立中…" : "＋建立為產品"}
          </button>
        ) : card.status === "unreadable" ? (
          <>
            <button type="button" onClick={onManual} className="rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground hover:border-primary hover:text-primary">自己填</button>
            <button type="button" onClick={onSkip} className="text-xs text-muted-foreground hover:underline">略過</button>
          </>
        ) : (
          <button type="button" disabled={retrying} onClick={onRetry} className="rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-50">
            {retrying ? "重讀中…" : "再試一次"}
          </button>
        )}
      </div>
    </div>
  );
}

function PhotoThumbnail({ brandId, photoName }: { brandId: string; photoName: string | undefined }) {
  // 照片路由要求登入，而 <img> 自己發的請求不會帶權杖——所以繞 apiFetch 拿，
  // 見 useAuthedImage 檔頭（2026-08-30 實機驗收抓到的，本來就壞）。
  const url = photoName
    ? `/brands/${encodeURIComponent(brandId)}/intake/photos/${encodeURIComponent(photoName)}`
    : undefined;
  const { src, failed } = useAuthedImage(url);
  if (!src) {
    return <span aria-label={failed ? "沒有可用照片縮圖" : "照片縮圖載入中"} className="flex h-14 w-14 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground"><ImageOff className="h-5 w-5" aria-hidden="true" /></span>;
  }
  return (
    <img
      src={src}
      alt="這張產品卡的來源照片"
      width={56}
      height={56}
      className="h-14 w-14 shrink-0 rounded-md object-cover"
    />
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
