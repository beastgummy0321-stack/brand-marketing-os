import { useState } from "react";
import { X } from "lucide-react";
import { SidePanel } from "@/components/layout/SidePanel";
import { COST_PRODUCT_SCAN, createProduct, startProductResearch } from "@/lib/productsApi";
import { PanelSaveButton } from "../shared/PanelSaveButton";

const URL_FORMAT_ERROR =
  "這個網址看起來不完整，記得從 https:// 開始，例如「https://example.com/products/xxx」。";

/** 新增產品側板（契約 S6.8–S6.14）：兩顆送出鈕共用同一組欄位——「新增這個產品」純手動、
 * 同步、免費；「AI 幫我調研」網址必填，同步建立產品後在背景開始調研（拿不準的點 1，本檔
 * 採契約目前的設計 A：先建產品、失敗留空產品讓使用者自己處理）。 */
export function ProductNewPanel({
  brandId,
  onClose,
  onCreated,
}: {
  brandId: string;
  onClose: () => void;
  onCreated: (productId: string) => void;
}) {
  const [name, setName] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [pending, setPending] = useState<"manual" | "research" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submitManual() {
    setPending("manual");
    setError(null);
    try {
      const { id } = await createProduct(brandId, { name, source_url: sourceUrl });
      onCreated(id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "新增失敗，請稍後再試。");
    } finally {
      setPending(null);
    }
  }

  async function submitResearch() {
    const trimmedUrl = sourceUrl.trim();
    if (!/^https:\/\//.test(trimmedUrl)) {
      setError(URL_FORMAT_ERROR);
      return;
    }
    setPending("research");
    setError(null);
    try {
      const { product_id } = await startProductResearch(brandId, { name, source_url: trimmedUrl });
      onCreated(product_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "送出失敗，請稍後再試。");
    } finally {
      setPending(null);
    }
  }

  return (
    <SidePanel ariaLabel="新增產品" onClose={onClose}>
      <div className="flex items-start justify-between gap-3 border-b border-border pb-4">
        <h2 className="font-display text-lg text-foreground">新增產品</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="關閉側板"
          className="rounded-md p-2 text-muted-foreground hover:bg-muted"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>

      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          void submitManual();
        }}
      >
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">產品名稱</span>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            placeholder="例如「薑黃暖薑飲 30 包盒裝」"
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">產品頁網址（選填，填了才能用 AI 調研）</span>
          <input
            type="text"
            value={sourceUrl}
            onChange={(e) => setSourceUrl(e.target.value)}
            placeholder="https://example.com/products/xxx"
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
        </label>

        {error && <p className="text-sm text-danger">{error}</p>}

        <div className="flex flex-col gap-2">
          <PanelSaveButton
            saving={pending !== null}
            label="新增這個產品"
            pendingLabel="處理中…"
          />
          <button
            type="button"
            disabled={pending !== null}
            onClick={() => void submitResearch()}
            className="rounded-md border border-primary px-4 py-2 text-sm font-medium text-primary hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {pending === "research" ? "處理中…" : `AI 幫我調研（預估 US$${COST_PRODUCT_SCAN.toFixed(2)}）`}
          </button>
        </div>
      </form>
    </SidePanel>
  );
}
