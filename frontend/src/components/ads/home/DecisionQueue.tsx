import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import type { QueuePayload, TriageClass } from "@/lib/adsTriageApi";

const TONE: Record<TriageClass, string> = {
  stop_loss: "bg-danger/10 text-danger",
  worse: "bg-warning/10 text-warning",
  better: "bg-success/10 text-success",
  flat: "bg-muted text-muted-foreground",
  insufficient: "bg-muted text-muted-foreground",
  no_target: "bg-muted text-muted-foreground",
};

const num = (value: number | null) => (value === null ? "未知" : value.toLocaleString("zh-TW"));

/** 品牌決定佇列（F19-I02 版面骨架；列內容細節留給 I03）：`queue.items` 已經是「還需要你決定」
 * 的停損／變差廣告——後端只回還開著、分類仍成立的列（`app/ads/triage.py::_queue_payload`），
 * 這支不再自己過濾或重算門檻，`item.action_url` 直接帶去對應活動的成效分頁。 */
export function DecisionQueue({ queue }: { queue: QueuePayload }) {
  if (queue.items.length === 0) {
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
      {queue.items.map((item) => {
        const t = item.triage;
        return (
          <div key={item.id} className="flex items-center gap-4 p-4">
            <span className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-semibold ${TONE[t.class]}`}>
              {t.label}
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold">{t.name ?? "（未命名廣告）"}</p>
              <p className="numeric mt-1 text-xs text-muted-foreground">
                {t.current.result_kind ?? "成本"} {num(t.current.cost_per_result)}・目標 {num(t.target.value)}
              </p>
            </div>
            <Button asChild size="sm" variant="outline">
              <Link to={item.action_url ?? `/brands/${item.brand_id ?? ""}/ads`}>查看</Link>
            </Button>
          </div>
        );
      })}
    </div>
  );
}
