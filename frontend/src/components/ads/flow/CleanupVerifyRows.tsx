import { Chip } from "../patterns";
import type { ChangeItem } from "@/lib/adsChangeApi";
import { Tile } from "./Tile";

/** The stored reason a read could not prove an item (`evidence_json.message`, written by the read-back —
 * `app/ads/change_control_verify.py`); anything else in that bag is not ours to interpret. */
export function readbackMessage(item: ChangeItem): string | undefined {
  const value = item.evidence_json.message;
  return typeof value === "string" ? value : undefined;
}

/** 核對結果頁的逐列狀態：一則廣告一列，各自的狀態；跟 `ConfirmPage`／`CleanupEvidence` 同一顆縮圖零件。
 * F49 Contract B: the chip is the served `verification_label` (no local word table); an `unknown` row (read, but not
 * provable) prints the stored reason beside it, so it never reads like `reported` (not read yet). */
export function CleanupVerifyRows({ items }: { items: ChangeItem[] }) {
  return (
    <div className="divide-y divide-border rounded-xl border border-border bg-card">
      {items.map((item) => {
        const reason = item.verification_state === "unknown" ? readbackMessage(item) : undefined;
        return (
          <div key={item.id} className="flex items-center gap-3 px-4 py-3">
            <Tile url={null} size="sm" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium" title={item.target.name ?? undefined}>
                {item.target.name ?? "（未命名廣告）"}
              </p>
              {reason && <p className="mt-0.5 text-xs text-muted-foreground">{reason}</p>}
            </div>
            <Chip tone={item.verification_state === "confirmed" ? "ok" : item.verification_state === "deviated" || item.verification_state === "stale" ? "bad" : "neutral"}>
              {item.verification_label ?? "—"}
            </Chip>
          </div>
        );
      })}
    </div>
  );
}
