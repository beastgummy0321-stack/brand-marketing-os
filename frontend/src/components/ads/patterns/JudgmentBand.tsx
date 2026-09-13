import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

/** 頁首判斷帶（F04-I07）：整句判斷歸程式組字串出來，元件原樣印，不拼、不重算。
 * 沒有插畫欄位、沒有第三行、沒有按鈕（R3：判斷帶不放插畫／吉祥物）。 */
export function JudgmentBand({
  icon: Icon,
  sentence,
  facts,
  tone = "neutral",
}: {
  icon: LucideIcon;
  sentence: string;
  facts?: string;
  tone?: "neutral" | "good" | "warn";
}) {
  const toneClass =
    tone === "good" ? "text-success" : tone === "warn" ? "text-warning" : "text-primary";

  return (
    <div className="flex items-center gap-4 rounded-xl border border-border bg-accent/60 p-5">
      <div className="flex size-11 shrink-0 items-center justify-center rounded-full bg-accent">
        <Icon className={cn("size-5", toneClass)} />
      </div>
      <div className="flex flex-col gap-1">
        <p className="text-base font-semibold sm:text-lg">{sentence}</p>
        {facts && <p className="text-sm text-muted-foreground">{facts}</p>}
      </div>
    </div>
  );
}
