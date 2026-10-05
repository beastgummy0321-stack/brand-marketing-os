import { ArrowUpRight, CheckCheck } from "lucide-react";
import { Link } from "react-router-dom";
import { Badge } from "@/components/layout/ui/badge";
import { Button } from "@/components/layout/ui/button";
import type { InboxItem } from "@/lib/inboxApi";
import { formatInstant, useOrgClock } from "@/lib/orgClock";
import { SEVERITY_DOT_CLASS, SEVERITY_LABEL } from "@/lib/severity";
import { cn } from "@/lib/utils";

/** F50-I14 (Contract K): `YYYY/MM/DD HH:mm` on the org's clock, not the viewer's zone; "" when unreadable. */
function resolvedStamp(iso: string | null, tz: string): string {
  const day = formatInstant(iso, tz, "ymd");
  return day ? `${day} ${formatInstant(iso, tz, "hm")}` : "";
}

/** 緊湊清單列：全文與操作集中在右侧詳情，避免一長串重複按鈕。 */
export function InboxItemCard({ item, selected, onSelect }: { item: InboxItem; selected: boolean; onSelect: () => void }) {
  return <li className="border-b border-border last:border-b-0">
    <button type="button" onClick={onSelect} aria-pressed={selected} className={cn("flex w-full flex-col gap-2 px-5 py-4 text-left hover:bg-muted/60", selected && "bg-accent/65")}>
      <span className="flex w-full items-center justify-between gap-3 text-xs">
        <span className="truncate font-medium text-foreground">{item.brand_name ?? "全站"}</span>
        <Severity item={item} />
      </span>
      <span className="line-clamp-2 text-sm leading-6 text-foreground">{item.message}</span>
      <span className="text-xs text-muted-foreground">{item.category_label}</span>
    </button>
  </li>;
}

function Severity({ item }: { item: InboxItem }) {
  return <span className="inline-flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground">
    <span className={cn("size-1.5 rounded-full", SEVERITY_DOT_CLASS[item.severity])} aria-hidden="true" />
    {SEVERITY_LABEL[item.severity]}
  </span>;
}

export function InboxItemDetail({ item, variant, resolving, busy, error, onResolve }: {
  item: InboxItem;
  variant: "open" | "done";
  resolving: boolean;
  busy: boolean;
  error?: string;
  onResolve: (id: string) => void;
}) {
  const clock = useOrgClock();
  const resolved = resolvedStamp(item.resolved_at, clock.timezone);
  return <section aria-label="事項詳情" className="flex min-w-0 flex-col gap-6 p-6">
    <div className="flex flex-wrap items-center gap-2">
      <Badge variant="secondary">{item.brand_name ?? "全站"}</Badge>
      <Badge variant="outline">{item.category_label}</Badge>
      <Severity item={item} />
    </div>
    <div className="flex flex-col gap-3">
      <h2 className="text-lg font-semibold">事項詳情</h2>
      <p className="whitespace-pre-wrap text-sm leading-7 text-foreground">{item.message}</p>
    </div>
    {variant === "done" && <div className="flex items-center gap-2 rounded-lg bg-muted/60 p-3 text-sm text-muted-foreground">
      <CheckCheck className="size-4" aria-hidden="true" />
      {resolved ? `已標記處理於 ${resolved}` : "已標記處理"}
    </div>}
    {error && <p role="alert" className="text-sm text-danger">{error}</p>}
    <div className="flex flex-wrap items-center gap-3 border-t border-border pt-5">
      {item.action_url && <Button variant="outline" asChild><Link to={item.action_url}>前往詳情<ArrowUpRight className="size-4" aria-hidden="true" /></Link></Button>}
      {variant === "open" && <Button type="button" onClick={() => onResolve(item.id)} busy={busy}>{resolving ? "標記中…" : "標記已處理"}</Button>}
    </div>
  </section>;
}
