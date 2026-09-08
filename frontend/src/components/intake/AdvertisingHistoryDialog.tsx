import { Button } from "@/components/layout/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from "@/components/layout/ui/dialog";
import { setAdvertisingHistory } from "@/lib/libraryApi";
import { useFormSubmit } from "@/lib/useFormSubmit";

/** 票 past-ads/04（ADR 0067 §1.6）：新品牌的分岔——建檔精靈第一步送出的當下問一次，
 * 在導頁之前（`IntakeWizard.tsx` 的 `brandId === null` 分支）。兩顆按鈕、沒有欄位，讀作
 * Confirm 樣式（design-system §6：沒有模態表單），不是表單：沒有關閉鈕、點遮罩沒反應、
 * ESC 沒反應，唯一離開的路是按下其中一顆按鈕。 */
export function AdvertisingHistoryDialog({
  brandId,
  onChosen,
}: {
  brandId: string;
  onChosen: () => void;
}) {
  const { saving, error, submit } = useFormSubmit(async (value: "has_history" | "none") => {
    await setAdvertisingHistory(brandId, value);
    onChosen();
  });

  return (
    <Dialog open onOpenChange={() => {}}>
      <DialogContent
        showCloseButton={false}
        onEscapeKeyDown={(e) => e.preventDefault()}
        onPointerDownOutside={(e) => e.preventDefault()}
        onInteractOutside={(e) => e.preventDefault()}
      >
        <DialogTitle>這個品牌以前投放過廣告嗎？</DialogTitle>
        <DialogDescription>兩種都能建檔；選了之後可以在品牌頁改。</DialogDescription>
        {error && <p className="text-sm text-danger">{error}</p>}
        <DialogFooter>
          <Button type="button" variant="outline" disabled={saving} onClick={() => void submit("none")}>
            完全沒投放過
          </Button>
          <Button type="button" disabled={saving} onClick={() => void submit("has_history")}>
            投放過廣告
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
