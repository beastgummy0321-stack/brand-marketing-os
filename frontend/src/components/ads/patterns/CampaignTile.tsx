import { Badge } from "@/components/layout/ui/badge";

/** Campaign 卡（F04-I07）：所有數字都是呼叫端已經格式化好的字串——元件不算數、不自己印 0
 * （design-system §7「誠實的空狀態」）。`percent` 只給進度條寬度，超過 100 一律夾在 100。 */
export function CampaignTile({
  name,
  statusLabel,
  meta,
  spendText,
  budgetText,
  percentText,
  percent,
  judgment,
  judgmentDetail,
  onClick,
  statusTone = "secondary",
}: {
  name: string;
  statusLabel: string;
  meta: string;
  spendText: string;
  budgetText: string;
  percentText: string;
  percent: number;
  judgment: string;
  judgmentDetail: string;
  onClick?: () => void;
  statusTone?: "secondary" | "default" | "outline";
}) {
  const width = Math.min(100, Math.max(0, percent));

  return (
    <article
      className="surface flex cursor-pointer flex-col gap-2 p-4 transition-shadow hover:shadow-[var(--shadow-card-hover)]"
      onClick={onClick}
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="truncate text-[15px] font-semibold">{name}</h3>
        <Badge variant={statusTone}>{statusLabel}</Badge>
      </div>
      <p className="text-xs text-muted-foreground">{meta}</p>
      <div className="flex items-baseline justify-between gap-2">
        <span className="numeric text-sm">
          {spendText} / {budgetText}
        </span>
        <span className="numeric text-sm text-muted-foreground">{percentText}</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-primary" style={{ width: `${width}%` }} />
      </div>
      <div className="rounded-lg bg-accent/60 px-3 py-2">
        <p className="text-sm font-semibold">{judgment}</p>
        <p className="text-xs text-muted-foreground">{judgmentDetail}</p>
      </div>
    </article>
  );
}
