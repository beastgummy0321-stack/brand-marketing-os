import { Button } from "@/components/layout/ui/button";
import { useEffect, useState } from "react";
import { deleteProduct, fetchDeleteImpact, type ProductDeleteImpact } from "@/lib/productsApi";
import { SidePanel } from "@/components/layout/SidePanel";
import { useFormSubmit } from "@/lib/useFormSubmit";

/** 永久刪除產品側板（契約 S6.49–S6.56）：文案與清點清單跟品牌智庫「永久刪除品牌」
 * 同一套慣例（`components/library/panels/BrandProfilePanel.tsx` 的 `ConfirmDeleteView`），
 * 只是這裡一開就是確認畫面——入口本身只在已封存產品才顯示（S6.20），不用像品牌那樣先給
 * 一段「請先封存」的中繼畫面。 */
export function ProductDeletePanel({
  brandId,
  productId,
  productName,
  onClose,
  onDeleted,
}: {
  brandId: string;
  productId: string;
  productName: string;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const [impact, setImpact] = useState<ProductDeleteImpact[] | null>(null);
  const [impactError, setImpactError] = useState<string | null>(null);
  const [confirmName, setConfirmName] = useState("");

  useEffect(() => {
    fetchDeleteImpact(brandId, productId)
      .then(setImpact)
      .catch((err: unknown) => setImpactError(err instanceof Error ? err.message : "讀取失敗，請稍後再試。"));
  }, [brandId, productId]);

  const form = useFormSubmit(async () => {
    await deleteProduct(brandId, productId, confirmName);
    onDeleted();
  });

  return (
    <SidePanel ariaLabel={`永久刪除產品「${productName}」`} onClose={onClose}>
      <div className="border-b border-border pb-4">
        <h2 className="font-display text-lg text-foreground">永久刪除產品「{productName}」</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          這個動作不能復原。刪掉之後，這個產品與底下所有資料都會從系統消失，只在稽核紀錄留下一筆「誰在什麼時候刪了什麼」。
        </p>
      </div>

      <div className="rounded-md border border-danger/40 bg-danger/5 p-3 text-sm">
        <p className="font-medium text-foreground">會一起消失的資料：</p>
        {impactError ? (
          <p className="mt-1 text-danger">{impactError}</p>
        ) : impact === null ? (
          <p className="mt-1 text-muted-foreground">讀取中…</p>
        ) : impact.length === 0 ? (
          <p className="mt-1 text-muted-foreground">這個產品底下目前沒有任何資料。</p>
        ) : (
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-muted-foreground">
            {impact.map((row) => (
              <li key={row.label}>
                {row.label} {row.count} 筆
              </li>
            ))}
          </ul>
        )}
        <p className="mt-2 text-xs text-muted-foreground">
          系統會在刪除前自動把整個資料庫備份一份到 backups 資料夾，萬一刪錯還救得回來。
        </p>
      </div>

      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          void form.submit();
        }}
      >
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-foreground">請輸入產品名稱以確認</span>
          <input
            type="text"
            value={confirmName}
            onChange={(e) => setConfirmName(e.target.value)}
            autoComplete="off"
            placeholder={productName}
            className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
          />
          <span className="text-xs text-muted-foreground">要刪除的產品是「{productName}」，請一字不差地打一次。</span>
        </label>

        {form.error && <p className="text-sm text-danger">{form.error}</p>}
        <div className="flex items-center gap-3">
          <Button variant="outline" size="sm"
            type="submit"
            busy={form.saving}
            className="rounded-md bg-danger px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {form.saving ? "刪除中…" : "永久刪除這個產品"}
          </Button>
          <Button variant="outline" size="sm"
            type="button"
            onClick={onClose}
            busy={form.saving}
            className="text-sm text-muted-foreground hover:underline"
          >
            取消
          </Button>
        </div>
      </form>
    </SidePanel>
  );
}
