import type { LucideIcon } from "lucide-react";
import { Badge } from "@/components/layout/ui/badge";
import { Button } from "@/components/layout/ui/button";

export interface DecisionItem {
  id: string;
  icon: LucideIcon;
  title: string;
  reason: string;
}

/** 需要你決定卡（F04-I07）：F04 沒有產生端，`items` 目前一律是空陣列，元件本身要能給
 * F05 直接餵資料用，onAgree/onDefer/onWhy 缺就把按鈕停用，不是隱藏。 */
export function DecisionCard({
  items,
  onAgree,
  onDefer,
  onWhy,
  busy = false,
  disabledReason,
}: {
  items: DecisionItem[];
  busy?: boolean;
  disabledReason?: string | null;
  onAgree?: (id: string) => void;
  onDefer?: (id: string) => void;
  onWhy?: (id: string) => void;
}) {
  return (
    <div className="surface">
      <div className="surface-header">
        <h2>需要你決定</h2>
        {items.length > 0 && <Badge variant="secondary">{items.length}</Badge>}
      </div>
      <div className="surface-body">
        {items.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">目前沒有需要你決定的事</p>
        ) : (
          <div className="flex flex-col gap-4">
            {items.map((item) => {
              const Icon = item.icon;
              return (
                <div key={item.id} className="flex items-start gap-3 border-t border-border pt-4 first:border-t-0 first:pt-0">
                  <div className="flex size-12 shrink-0 items-center justify-center rounded-lg bg-accent">
                    <Icon className="size-5 text-primary" />
                  </div>
                  <div className="flex-1">
                    <p className="text-sm font-semibold">{item.title}</p>
                    <p className="text-xs text-muted-foreground">{item.reason}</p>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <Button size="sm" busy={busy} disabledReason={disabledReason || (!onAgree ? "目前還不能同意這項決定" : undefined)} onClick={() => onAgree?.(item.id)}>
                      同意
                    </Button>
                    <Button size="sm" variant="outline" busy={busy} disabledReason={disabledReason || (!onDefer ? "目前還不能延後這項決定" : undefined)} onClick={() => onDefer?.(item.id)}>
                      先不要
                    </Button>
                    <Button size="sm" variant="outline" busy={busy} disabledReason={disabledReason || (!onWhy ? "目前還不能查看原因" : undefined)} onClick={() => onWhy?.(item.id)}>
                      查看原因
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
