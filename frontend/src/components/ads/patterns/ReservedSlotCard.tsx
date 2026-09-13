import { Badge } from "@/components/layout/ui/badge";

/** 佔位卡（F04-I07）：席位保留不是拒絕。文案不得出現「不支援」「無法」「尚未開放使用」，
 * 一律「…接上後開放」。整張灰階、不可點、沒有按鈕（連 disabled 假按鈕都不要）。 */
export function ReservedSlotCard({
  title,
  description,
  tag,
  bullets,
}: {
  title: string;
  description: string;
  tag: string;
  bullets?: string[];
}) {
  return (
    <div className="rounded-xl border border-border bg-muted p-5 text-muted-foreground">
      <div className="flex items-start justify-between gap-3">
        <p className="text-[15px] font-semibold text-muted-foreground">{title}</p>
        <Badge variant="secondary">{tag}</Badge>
      </div>
      <p className="mt-1 text-sm text-muted-foreground">{description}</p>
      {bullets && bullets.length > 0 && (
        <ul className="mt-3 flex flex-col gap-1 text-xs text-muted-foreground">
          {bullets.map((bullet) => (
            <li key={bullet}>・{bullet}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
