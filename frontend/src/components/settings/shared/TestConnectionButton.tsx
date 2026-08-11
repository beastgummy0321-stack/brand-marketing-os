import { useState } from "react";
import { Check, X } from "lucide-react";

type Result = "success" | "error" | null;

/** 測試連線按鈕（票 B1-settings，契約 S15.6／S15.12／S15.18）：這三顆按鈕本來就是真的
 * 打外部 API、AI 金鑰那顆還真的會扣款，本票安全規則明講原型階段不接線、不送任何請求。
 * 點下去只在前端「成功」「失敗」兩種假結果之間循環展示，讓兩版文案都能點出來看；
 * 之後接線階段才換成真的呼叫（後端路徑已留，見契約「要新增的 API」節）。 */
export function TestConnectionButton({
  description,
  successMessage,
  errorMessage,
}: {
  description: string;
  successMessage: string;
  errorMessage: string;
}) {
  const [result, setResult] = useState<Result>(null);

  function handleClick() {
    setResult((prev) => (prev === null ? "success" : prev === "success" ? "error" : null));
  }

  return (
    <div className="flex flex-col gap-2 border-t border-border pt-4">
      <p className="text-sm text-muted-foreground">{description}</p>
      <div>
        <button
          type="button"
          onClick={handleClick}
          className="rounded-md border border-border px-4 py-2 text-sm font-medium text-foreground hover:border-primary hover:text-primary"
        >
          測試連線
        </button>
      </div>
      {result === "success" && (
        <p className="flex items-center gap-1.5 text-sm font-medium text-success">
          <Check className="h-4 w-4" aria-hidden="true" />
          {successMessage}
        </p>
      )}
      {result === "error" && (
        <p className="flex items-center gap-1.5 text-sm font-medium text-danger">
          <X className="h-4 w-4" aria-hidden="true" />
          {errorMessage}
        </p>
      )}
    </div>
  );
}
