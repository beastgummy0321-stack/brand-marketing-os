import type { InboxItem } from "@/lib/inboxApi";
import { SEVERITY_DOT_CLASS, SEVERITY_LABEL } from "@/lib/severity";
import { cn } from "@/lib/utils";

/** 相對時間（S2.12「結案於 X」）：只有這一個呼叫端，不抽成 lib 工具函式。 */
function relativeDays(iso: string): string {
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / (1000 * 60 * 60 * 24));
  if (days <= 0) return "今天";
  if (days === 1) return "1 天前";
  return `${days} 天前`;
}

/** 收件匣單一卡片（票 B1-inbox）：待辦／已結共用同一顆，`variant` 決定要不要「知道了」
 * 按鈕（S2.8，已結清單沒有）與是否顯示結案時間（S2.12）。 */
export function InboxItemCard({
  item,
  variant,
  resolving = false,
  error,
  onResolve,
  onOpenPrototypePanel,
}: {
  item: InboxItem;
  variant: "open" | "done";
  resolving?: boolean;
  error?: string;
  onResolve?: (id: string) => void;
  /** category === "prototype_phase_ended" 時，「詳情」開側板而不是外部連結（S2.7 唯一例外）。 */
  onOpenPrototypePanel?: () => void;
}) {
  const isPrototypeDetail = item.category === "prototype_phase_ended";

  return (
    <li className="flex flex-col gap-2 rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)]">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-wrap items-center gap-2 text-xs">
          <span
            className="max-w-[16rem] truncate rounded-full bg-muted px-2 py-0.5 font-medium text-foreground"
            title={item.brand_name ?? "全站"}
          >
            {item.brand_name ?? "全站"}
          </span>
          <span className="flex items-center gap-1.5 text-muted-foreground">
            <span
              className={cn("h-2 w-2 shrink-0 rounded-full", SEVERITY_DOT_CLASS[item.severity])}
              aria-hidden="true"
            />
            {SEVERITY_LABEL[item.severity]}
          </span>
          <span className="text-muted-foreground">{item.category_label}</span>
        </div>
        {item.action_url &&
          (isPrototypeDetail ? (
            <button
              type="button"
              onClick={onOpenPrototypePanel}
              className="shrink-0 text-sm text-primary underline-offset-4 hover:underline"
            >
              詳情
            </button>
          ) : (
            <a
              href={item.action_url}
              className="shrink-0 text-sm text-primary underline-offset-4 hover:underline"
            >
              詳情
            </a>
          ))}
      </div>

      <p className="text-sm text-foreground">{item.message}</p>

      {variant === "done" && item.resolved_at && (
        <p className="text-xs text-muted-foreground">結案於 {relativeDays(item.resolved_at)}</p>
      )}

      {variant === "open" && (
        <div className="flex items-center justify-between gap-3">
          {error ? <p className="text-xs text-danger">{error}</p> : <span />}
          {(
            <button
              type="button"
              onClick={() => onResolve?.(item.id)}
              disabled={resolving}
              className="shrink-0 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
            >
              {resolving ? "處理中…" : "知道了"}
            </button>
          )}
        </div>
      )}
    </li>
  );
}
