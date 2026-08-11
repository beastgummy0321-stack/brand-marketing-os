import { useState } from "react";
import { ImageOff } from "lucide-react";
import { EmptyState } from "@/components/layout/EmptyState";
import { Pager } from "@/components/layout/Pager";
import { deleteAsset, type LibraryAsset, type LibraryProductOption } from "@/lib/libraryApi";
import { usePagination } from "@/lib/usePagination";
import { Badge } from "../shared/Badge";
import { InlineDeleteButton } from "../shared/InlineDeleteButton";
import { AssetUploadPanel } from "../panels/AssetUploadPanel";

/** 官方素材分頁（契約 S5.23–S5.27）：卡片格線，只有刪除、沒有修改（換圖就刪掉重傳），
 * 超過 12 張分頁（互動鐵則⑥）。 */
export function AssetsTab({
  brandId,
  assets,
  products,
  onChanged,
}: {
  brandId: string;
  assets: LibraryAsset[];
  products: LibraryProductOption[];
  onChanged: () => void;
}) {
  const [uploadOpen, setUploadOpen] = useState(false);
  const { page, pageCount, totalCount, pageItems, goToPage, topRef } = usePagination(assets);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="font-display text-lg text-foreground">官方素材</h2>
        <button
          type="button"
          onClick={() => setUploadOpen(true)}
          className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90"
        >
          上傳素材
        </button>
      </div>

      {assets.length === 0 ? (
        <EmptyState
          title="這個品牌還沒有官方素材"
          description="Logo、產品照、包裝設計等正式圖檔，上傳後之後產出內容時可以直接取用。"
        />
      ) : (
        <div ref={topRef} className="flex flex-col gap-3">
          <div className="grid grid-cols-4 gap-4">
            {pageItems.map((asset) => (
              <AssetCard
                key={asset.id}
                asset={asset}
                brandId={brandId}
                onDeleted={onChanged}
              />
            ))}
          </div>
          <Pager page={page} pageCount={pageCount} totalCount={totalCount} onChange={goToPage} />
        </div>
      )}

      {uploadOpen && (
        <AssetUploadPanel
          brandId={brandId}
          products={products}
          onClose={() => setUploadOpen(false)}
          onSaved={() => {
            setUploadOpen(false);
            onChanged();
          }}
        />
      )}
    </div>
  );
}

function AssetCard({
  asset,
  brandId,
  onDeleted,
}: {
  asset: LibraryAsset;
  brandId: string;
  onDeleted: () => void;
}) {
  const [broken, setBroken] = useState(false);

  return (
    <div className="flex flex-col overflow-hidden rounded-md border border-border bg-card shadow-[var(--shadow-card)]">
      <div className="flex aspect-[4/3] items-center justify-center bg-muted">
        {broken ? (
          <div className="flex flex-col items-center gap-1 text-xs text-muted-foreground">
            <ImageOff className="h-6 w-6" aria-hidden="true" />
            圖片載入失敗
          </div>
        ) : (
          <img
            src={asset.file_url}
            alt={asset.title ?? asset.asset_kind_label}
            loading="lazy"
            className="h-full w-full object-cover"
            onError={() => setBroken(true)}
          />
        )}
      </div>
      <div className="flex flex-col gap-1.5 p-3">
        <Badge>{asset.asset_kind_label}</Badge>
        <p className="truncate text-sm text-foreground" title={asset.title ?? undefined}>
          {asset.title ?? "（未命名）"}
          {asset.product_name && (
            <span className="text-muted-foreground">
              <span aria-hidden="true"> ・ </span>
              {asset.product_name}
            </span>
          )}
        </p>
        <InlineDeleteButton
          confirmText="確定要刪除這個素材檔案？"
          onDelete={async () => {
            await deleteAsset(brandId, asset.id);
            onDeleted();
          }}
        />
      </div>
    </div>
  );
}
