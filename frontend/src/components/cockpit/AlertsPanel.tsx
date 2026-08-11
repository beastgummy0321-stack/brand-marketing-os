import { useState } from "react";
import type { Alert } from "@/lib/api";
import { resolveAlert } from "@/lib/api";
import { SEVERITY_DOT_CLASS, SEVERITY_LABEL } from "@/lib/severity";
import { cn } from "@/lib/utils";

/** 異常警示區（票 05-alerts-fuel-pipeline）：直接讀打斷佇列，按嚴重度分色；一鍵
 * 「知道了」／「詳情」沿用既有 resolve 行為（見 `lib/api.ts` resolveAlert 註解）。
 * 沒有警報顯示「一切正常」（規格使用者故事 10 的同一原則，套用到警示區）。 */

export function AlertsPanel({
  alerts,
  onResolved,
}: {
  alerts: Alert[];
  /** 「知道了」成功後呼叫，讓上層重新抓一次駕駛艙資料（本元件不自行維護清單狀態，
   * 避免跟 KPI／指南卡等其他區塊各自對不齊）。 */
  onResolved: () => void;
}) {
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleResolve(id: string) {
    setResolvingId(id);
    setError(null);
    try {
      await resolveAlert(id);
      onResolved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "「知道了」失敗，請稍後再試。");
    } finally {
      setResolvingId(null);
    }
  }

  return (
    <div
      data-tour="alerts"
      className="flex flex-col gap-3 rounded-lg border border-border bg-card p-5 shadow-[var(--shadow-card)]"
    >
      <h2 className="font-display text-base text-foreground">異常警示</h2>
      {error && <p className="text-xs text-danger">{error}</p>}
      {alerts.length === 0 ? (
        <p className="text-sm text-muted-foreground">一切正常，目前沒有警示。</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {alerts.map((alert) => (
            <li
              key={alert.id}
              className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2 text-sm"
            >
              <span className="flex min-w-0 items-center gap-2">
                <span
                  className={cn("h-2.5 w-2.5 shrink-0 rounded-full", SEVERITY_DOT_CLASS[alert.severity])}
                  aria-hidden="true"
                />
                <span className="shrink-0 text-xs text-muted-foreground">
                  {SEVERITY_LABEL[alert.severity]}
                </span>
                <span className="truncate text-foreground">{alert.message}</span>
              </span>
              <span className="flex shrink-0 items-center gap-3">
                {alert.action_url && (
                  <a
                    href={alert.action_url}
                    className="text-primary underline-offset-4 hover:underline"
                  >
                    詳情
                  </a>
                )}
                <button
                  type="button"
                  onClick={() => handleResolve(alert.id)}
                  disabled={resolvingId === alert.id}
                  className="rounded-md border border-border px-2 py-1 text-xs text-muted-foreground transition-colors hover:border-primary hover:text-primary disabled:opacity-50"
                >
                  {resolvingId === alert.id ? "處理中…" : "知道了"}
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
