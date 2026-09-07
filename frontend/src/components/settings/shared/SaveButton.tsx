/** 送出按鈕（票 B1-settings）：送出中鎖住＋文字換成人話進度（五鐵則④）。可逆動作（儲存）
 * 用「儲存中…」，不可逆動作（清除金鑰、重設規則卡）呼叫端傳 `pendingLabel="處理中…"`。 */
import { Button } from "@/components/layout/ui/button";

export function SaveButton({
  saving,
  label,
  pendingLabel = "儲存中…",
  variant = "primary",
}: {
  saving: boolean;
  label: string;
  pendingLabel?: string;
  variant?: "primary" | "secondary";
}) {
  return (
    <Button
      type="submit"
      disabled={saving}
      variant={variant === "primary" ? "default" : "outline"}
    >
      {saving ? pendingLabel : label}
    </Button>
  );
}
