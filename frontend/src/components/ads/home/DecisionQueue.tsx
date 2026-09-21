import { Plug } from "lucide-react";
import { Badge } from "@/components/layout/ui/badge";
import { Button } from "@/components/layout/ui/button";
import { Skeleton } from "@/components/layout/Skeleton";
import type { QueuePayload } from "@/lib/adsTriageApi";
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

/** 品牌決定佇列（F19-I03：v7 `home()` 的 `row`，prototype ≈ 195–203 落地到 `QueueRow`，這支管
 * 殼、空狀態跟 `kinds_pending` 佔位列）。`queue.items` 已經是「還需要你決定」的停損／變差廣
 * 告——後端只回還開著、分類仍成立的列（`app/ads/triage.py::_queue_payload`），這支不再自己過
 * 濾。loading／error 由呼叫端（`AdsHomePage`）的 `refreshQueue` 讀取狀態驅動
 * （review repair (b)：三個插槽各自獨立失敗，不拖累彼此）。
 *
 * 活動篩選缺口（issue F19-I03 已知差距）：v7 原型每個活動一顆篩選鈕，但 `QueuePayload`／
 * `TriageItem` 只帶 `campaign_id`，沒有活動名稱（F19-I01 契約；`AdsHomePage` 沒有另外把名稱
 * 傳進來，這支 touch 範圍也不准自己再打一支 API 去查）。不印 id 充當名稱，逐活動篩選鈕先不
 * 做，只留「全部 N」——等首頁把活動名稱一起帶下來，才把這顆補齊。 */
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

  const { items, kinds_pending } = state.queue;
  return (
    <div className="flex flex-col gap-3">
      {/* 空佇列不印「全部 0」——沒有東西好篩；「依活動篩選」的 role/aria-label 等 F19-I07
       * 真的有第二顆鈕再加回來，只有一顆的時候那組語意是假的（review fix）。 */}
      {items.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          <Badge>全部 {items.length}</Badge>
        </div>
      )}
      <div className="surface divide-y divide-border overflow-hidden">
        {/* 空佇列不重複印「都處理完了」——`AdsHomePage` 的頁首已經講過一次；這裡只留
         * `kinds_pending` 佔位列（review fix：同一頁一句話只講一次）。 */}
        {items.map((item, index) => <QueueRow key={item.id} item={item} primary={index === 0} />)}
        {kinds_pending.map((kind) => (
          <PendingRow key={kind} kind={kind} />
        ))}
      </div>
    </div>
  );
}
