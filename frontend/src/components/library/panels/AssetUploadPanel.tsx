import { useState } from "react";
import { X } from "lucide-react";
import { SidePanel } from "@/components/layout/SidePanel";
import { ASSET_KINDS, uploadAsset, type LibraryProductOption } from "@/lib/libraryApi";
import { useFormSubmit } from "@/lib/useFormSubmit";
import { PanelSaveButton } from "../shared/PanelSaveButton";

const ACCEPT = ".png,.jpg,.jpeg,.webp,.gif";

/** 上傳官方素材側板（契約 S5.27）：只有新增，沒有編輯（素材是檔案，要換圖就刪掉重傳，
 * 見 S5.26）。 */
export function AssetUploadPanel({
  brandId,
  products,
  onClose,
  onSaved,
}: {
  brandId: string;
  products: LibraryProductOption[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [assetKind, setAssetKind] = useState("");
  const [productId, setProductId] = useState("");
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);

  const form = useFormSubmit(async () => {
    if (!file) throw new Error("請先選擇圖檔。");
    await uploadAsset(brandId, { asset_kind: assetKind, product_id: productId, title, file });
    onSaved();
  });

  return (
    <SidePanel ariaLabel="上傳官方素材" onClose={onClose}>
      <div className="flex items-start justify-between gap-3 border-b border-border pb-4">
        <h2 className="font-display text-lg text-foreground">上傳官方素材</h2>
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
          void form.submit();
        }}
      >
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">圖檔</span>
          {/* B0-14 擴大修：中文「選擇檔案」按鈕；input 留在 DOM（sr-only）讓 required 驗證照常作用 */}
          <span className="w-fit cursor-pointer rounded-md border border-border bg-card px-4 py-2 font-medium text-foreground hover:bg-muted">選擇檔案</span>
          <input
            type="file"
            accept={ACCEPT}
            required
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="sr-only"
          />
          <span className={file ? "text-foreground" : "text-muted-foreground"}>{file ? `已選擇：${file.name}` : "未選擇任何檔案"}</span>
          <span className="text-xs text-muted-foreground">支援 png、jpg、jpeg、webp、gif。</span>
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">種類</span>
          <select
            value={assetKind}
            onChange={(e) => setAssetKind(e.target.value)}
            required
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          >
            <option value="" disabled>
              請選擇
            </option>
            {ASSET_KINDS.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">掛在哪個產品？</span>
          <select
            value={productId}
            onChange={(e) => setProductId(e.target.value)}
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          >
            <option value="">整個品牌</option>
            {products.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">標題（選填）</span>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="例如「主要 Logo 透明底」"
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
        </label>

        {form.error && <p className="text-sm text-danger">{form.error}</p>}
        <div>
          <PanelSaveButton saving={form.saving} label="上傳這個素材" pendingLabel="上傳中…" />
        </div>
      </form>
    </SidePanel>
  );
}
