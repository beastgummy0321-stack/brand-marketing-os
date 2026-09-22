import { Chip } from "../patterns";
import type { ChangeItem } from "@/lib/adsChangeApi";
import { Tile } from "./Tile";

const STATE_LABEL: Record<ChangeItem["verification_state"], string> = {
  pending: "尚未回報", reported: "已回報，核對中", unknown: "還沒能確認",
  confirmed: "已核對，已關閉", deviated: "與核准不符", stale: "設定已變，需重新檢討",
};

export const CLEANUP_HERO_TITLE: Record<ChangeItem["verification_state"], string> = {
  confirmed: "這批要清理的廣告都已經關閉",
  deviated: "有廣告的狀態跟核准的不一樣",
  stale: "有廣告的設定變了，原本的核准不再適用",
  reported: "還在等系統核對",
  unknown: "還沒能確認每一則的狀態",
  pending: "還有廣告沒回報到平台上的操作",
};

/** F27-I15 Contract F: 「一個 set 整體算哪個狀態」——跟 `app/ads/triage.py::_row_cleanup_proposal`
 * 同一顆「全部 confirmed 才算 confirmed，否則挑第一個不是 confirmed 的」規則，不是嚴重度排序；
 * 這樣佇列列的 `proposal.verification_state` 跟這裡畫出來的摘要永遠一致。 */
export function cleanupOverallState(items: ChangeItem[]): ChangeItem["verification_state"] {
  if (items.length === 0) return "pending";
  if (items.every((i) => i.verification_state === "confirmed")) return "confirmed";
  return items.find((i) => i.verification_state !== "confirmed")?.verification_state ?? "pending";
}

/** 核對結果頁的逐列狀態：一則廣告一列，各自的狀態；跟 `ConfirmPage`／`CleanupEvidence` 同一顆
 * 縮圖零件。 */
export function CleanupVerifyRows({ items }: { items: ChangeItem[] }) {
  return (
    <div className="divide-y divide-border rounded-xl border border-border bg-card">
      {items.map((item) => (
        <div key={item.id} className="flex items-center gap-3 px-4 py-3">
          <Tile url={null} size="sm" />
          <p className="min-w-0 flex-1 truncate text-sm font-medium" title={item.target.name ?? undefined}>
            {item.target.name ?? "（未命名廣告）"}
          </p>
          <Chip tone={item.verification_state === "confirmed" ? "ok" : item.verification_state === "deviated" || item.verification_state === "stale" ? "bad" : "neutral"}>
            {STATE_LABEL[item.verification_state]}
          </Chip>
        </div>
      ))}
    </div>
  );
}
