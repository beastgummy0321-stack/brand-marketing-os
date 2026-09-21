import { Plug } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/layout/ui/badge";
import { Button } from "@/components/layout/ui/button";
import { Skeleton } from "@/components/layout/Skeleton";
import { cn } from "@/lib/utils";
import type { QueueItem, QueuePayload } from "@/lib/adsTriageApi";
import { QueueRow } from "./QueueRow";

export type QueueState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; queue: QueuePayload };

// `app/ads/triage.py::KINDS_PENDING` — 固定兩個，永遠回這兩個代碼，中文說法只在前端。未認得
// 的代碼（例如以後新增但這支還沒更新）印「其他」，不要把原始代碼漏給使用者看。
const PENDING_LABEL: Record<string, string> = {
  scale_budget: "可加預算",
  refresh_creative: "補素材",
};
const PENDING_FALLBACK_LABEL = "其他";

/** `kinds_pending` 佔位列：灰階、不可點，跟 `ReservedSlotCard` 同一條規則——「接上後開放」不是
 * 「不支援」，連假按鈕都不做（feature F19 決定：pause／可加預算／補素材／每月回顧都只能佔位）。 */
function PendingRow({ kind }: { kind: string }) {
  return (
    <div className="flex items-center gap-4 bg-muted/60 p-4">
      <div className="flex size-12 shrink-0 items-center justify-center rounded-lg bg-muted" aria-hidden="true">
        <Plug className="size-5 text-muted-foreground" />
      </div>
      <p className="flex-1 text-sm font-medium text-muted-foreground">{PENDING_LABEL[kind] ?? PENDING_FALLBACK_LABEL}</p>
      <Badge variant="secondary">接上後開放</Badge>
    </div>
  );
}

/** v7 `home()` 的 `.filt`（prototype ≈ 216）：「全部 N」＋逐活動一顆，名稱與計數從
 * `queue.items` 自己算（F19-I07：`TriageItem.campaign_name` 到位，補齊 F19-I03 留白的篩選
 * 鈕），不再打一支 API。順序照活動第一次在佇列出現的順序，不額外排序。 */
function campaignGroups(items: QueueItem[]): { id: string; name: string; count: number }[] {
  const order: string[] = [];
  const byId = new Map<string, { name: string; count: number }>();
  for (const item of items) {
    const id = item.triage.campaign_id;
    const name = item.triage.campaign_name;
    if (!name) continue; // 沒有活動名稱（見 `TriageItem.campaign_name` 註解）就不成顆篩選鈕。
    const existing = byId.get(id);
    if (existing) {
      existing.count += 1;
    } else {
      byId.set(id, { name, count: 1 });
      order.push(id);
    }
  }
  return order.map((id) => ({ id, ...byId.get(id)! }));
}

/** 單一顆篩選鈕：真按鈕（鍵盤可達，原生 Tab 順序），`aria-pressed` 帶狀態，不是純視覺樣式
 * 差異。只有一個活動時也照印「全部 N」＋那顆活動 pill，跟 v7 一樣（Done #4）。 */
function FilterPill({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "max-w-48 truncate rounded-full border px-3.5 py-1 text-xs font-medium",
        active
          ? "border-primary bg-primary text-primary-foreground"
          : "border-border bg-background text-foreground hover:bg-muted",
      )}
    >
      {label}
    </button>
  );
}

/** 品牌決定佇列（F19-I03：v7 `home()` 的 `row`，prototype ≈ 195–203 落地到 `QueueRow`，這支管
 * 殼、活動篩選、空狀態跟 `kinds_pending` 佔位列）。`queue.items` 已經是「還需要你決定」的停損／
 * 變差廣告——後端只回還開著、分類仍成立的列（`app/ads/triage.py::_queue_payload`），這支不再
 * 自己過濾分類，只再依選定活動篩一次。loading／error 由呼叫端（`AdsHomePage`）的 `refreshQueue`
 * 讀取狀態驅動（review repair (b)：三個插槽各自獨立失敗，不拖累彼此）。 */
export function DecisionQueue({ state, onRetry }: { state: QueueState; onRetry: () => void }) {
  // Hooks 前必須跑在每次 render，不能被下面的 loading／error 提早 return 擋住。
  const [filter, setFilter] = useState<string>("all");

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

  const { items, kinds_pending } = state.queue;
  const groups = campaignGroups(items);
  const visible = filter === "all" ? items : items.filter((item) => item.triage.campaign_id === filter);
  return (
    <div className="flex flex-col gap-3">
      {/* 空佇列不印「全部 0」——沒有東西好篩。 */}
      {items.length > 0 && (
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="依活動篩選">
          <FilterPill label={`全部 ${items.length}`} active={filter === "all"} onClick={() => setFilter("all")} />
          {groups.map((g) => (
            <FilterPill key={g.id} label={`${g.name} ${g.count}`} active={filter === g.id} onClick={() => setFilter(g.id)} />
          ))}
        </div>
      )}
      <div className="surface divide-y divide-border overflow-hidden">
        {/* 空佇列不重複印「都處理完了」——`AdsHomePage` 的頁首已經講過一次；這裡只留
         * `kinds_pending` 佔位列（review fix：同一頁一句話只講一次）。primary 只落在「篩選後」
         * 第一列（Done #4）——換篩選時主按鈕跟著換,不是永遠釘在未篩選的第一列。 */}
        {visible.map((item, index) => <QueueRow key={item.id} item={item} primary={index === 0} />)}
        {kinds_pending.map((kind) => (
          <PendingRow key={kind} kind={kind} />
        ))}
      </div>
    </div>
  );
}
