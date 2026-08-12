import { Badge } from "./Badge";

/** AI 預填徽章＋一句理由（GRILL-B4R-performance.md S8R.2：樣式沿用 B3 建檔精靈「AI 建議選項
 * 附一句說明」既有款式，避免全站兩套 AI 標示視覺）。`isAiSuggested=false` 時文字改「系統
 * 預設」（S8R.5：品牌完全沒有數據可用時，誠實區分「這是算出來的」還是「這是寫死的預設」，
 * 不讓使用者誤以為每一次都有 AI 在背後算）。 */
export function AiBadge({ isAiSuggested = true, reason }: { isAiSuggested?: boolean; reason: string }) {
  return (
    <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
      <Badge tone={isAiSuggested ? "success" : "neutral"}>{isAiSuggested ? "AI 建議" : "系統預設"}</Badge>
      {reason}
    </p>
  );
}
