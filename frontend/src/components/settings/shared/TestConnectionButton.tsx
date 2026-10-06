import { Button } from "@/components/layout/ui/button";

/** 尚無正式檢測端點；不能把前端示範狀態當成真實連線結果。 */
export function TestConnectionButton({
  description,
}: {
  description: string;
  successMessage: string;
  errorMessage: string;
}) {
  return (
    <div className="flex flex-col gap-3 border-t border-border pt-4">
      <p className="max-w-[var(--width-prose)] text-sm leading-6 text-muted-foreground">{description}</p>
      <div><Button type="button" variant="outline" disabledReason="目前尚未提供連線檢測功能">測試連線尚未提供</Button></div>
      <p className="text-xs text-muted-foreground">尚未執行連線測試，也不會產生測試費用。</p>
    </div>
  );
}
