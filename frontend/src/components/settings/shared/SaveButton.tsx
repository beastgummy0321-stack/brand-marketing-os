/** 送出按鈕（票 B1-settings）：送出中鎖住＋文字換成人話進度（五鐵則④）。可逆動作（儲存）
 * 用「儲存中…」，不可逆動作（清除金鑰、重設規則卡）呼叫端傳 `pendingLabel="處理中…"`。
 *
 * F51 Contract S: `saved` (from `useFormSubmit`) prints 「已儲存」 beside the button (`role="status"`) until the
 * form changes again. F51 Contract D: while saving the button is `busy` (no sentence; the label says 儲存中…). */
import { Check } from "lucide-react";
import { Button } from "@/components/layout/ui/button";

export const SAVED_TEXT = "已儲存";

export function SaveButton({
  saving,
  saved = false,
  label,
  pendingLabel = "儲存中…",
  variant = "primary",
}: {
  saving: boolean;
  saved?: boolean;
  label: string;
  pendingLabel?: string;
  variant?: "primary" | "secondary";
}) {
  return (
    <span className="inline-flex flex-wrap items-center gap-3">
      <Button type="submit" busy={saving} variant={variant === "primary" ? "default" : "outline"}>
        {saving ? pendingLabel : label}
      </Button>
      {saved && !saving && (
        <span role="status" data-slot="saved" className="inline-flex items-center gap-1 text-sm text-success">
          <Check className="size-4" aria-hidden="true" />
          {SAVED_TEXT}
        </span>
      )}
    </span>
  );
}
