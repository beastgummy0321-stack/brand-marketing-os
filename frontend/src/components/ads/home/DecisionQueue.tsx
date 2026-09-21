import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { Skeleton } from "@/components/layout/Skeleton";
import type { QueuePayload, TriageClass } from "@/lib/adsTriageApi";

export type QueueState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; queue: QueuePayload };

const TONE: Record<TriageClass, string> = {
  stop_loss: "bg-danger/10 text-danger",
  worse: "bg-warning/10 text-warning",
  better: "bg-success/10 text-success",
  flat: "bg-muted text-muted-foreground",
  insufficient: "bg-muted text-muted-foreground",
  no_target: "bg-muted text-muted-foreground",
};

/** 品牌決定佇列（F19-I02 版面骨架；review repair (c)：只印分類 chip、廣告名稱與連結，
 * 不印任何金額或 `result_kind`——那些數字要等 F19-I06 的 `result_label` 才有依據，
 * 列的其餘內容是 I03 的範圍）。`queue.items` 已經是「還需要你決定」的停損／變差廣告——
 * 後端只回還開著、分類仍成立的列（`app/ads/triage.py::_queue_payload`），這支不再自己過濾。
 * loading／error 由呼叫端（`AdsHomePage`）的 `refreshQueue` 讀取狀態驅動，這支只管殼
 * （review repair (b)：三個插槽各自獨立失敗，不拖累彼此）。 */
export function DecisionQueue({ state, onRetry }: { state: QueueState; onRetry: () => void }) {
  if (state.status === "loading") {
    return (
      <div className="flex flex-col gap-2">
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-20 w-full" />
      </div>
    );
  }
  if (state.status === "error") {
    return (
      <div className="surface p-5">
        <div className="space-y-2">
          <p role="alert" className="text-sm text-warning">{state.message}</p>
          <Button variant="outline" size="sm" onClick={onRetry}>重新讀取</Button>
        </div>
      </div>
    );
  }
  if (state.queue.items.length === 0) {
    return (
      <div className="surface">
        <p className="px-5 py-10 text-center text-sm text-muted-foreground">
          目前沒有需要你決定的廣告。
        </p>
      </div>
    );
  }
  return (
    <div className="surface divide-y divide-border overflow-hidden">
      {state.queue.items.map((item) => {
        const t = item.triage;
        return (
          <div key={item.id} className="flex items-center gap-4 p-4">
            <span className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-semibold ${TONE[t.class]}`}>
              {t.label}
            </span>
            <p className="min-w-0 flex-1 truncate text-sm font-semibold">{t.name ?? "（未命名廣告）"}</p>
            {item.action_url && (
              <Button asChild size="sm" variant="outline">
                <Link to={item.action_url}>查看</Link>
              </Button>
            )}
          </div>
        );
      })}
    </div>
  );
}
