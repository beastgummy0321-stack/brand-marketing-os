import { Chip } from "../patterns";
import type { ChangeItem } from "@/lib/adsChangeApi";
import { Tile } from "./Tile";
import { formatInstant, useOrgClock } from "@/lib/orgClock";

/** The readback owner's stored reason; no local comparator decides whether it was provable. */
export function readbackMessage(item: ChangeItem): string | undefined {
  const value = item.evidence_json.message;
  return typeof value === "string" ? value : undefined;
}

/** Display source proof levels; these labels never decide whether settings match. */
export function materialProofText(value: unknown): string {
  return value === "media_verified" ? "平台素材已核對"
    : value === "user_verified" ? "已人工核對素材" : "素材尚未確認";
}

function proofTime(value: unknown, timezone: string): string | null {
  return typeof value === "string" ? formatInstant(value, timezone, "md_hm") || null : null;
}

/** Current observation, attempted read and earlier proof retain their own served identities. */
export function ReadbackProof({ item, showObserved = true }: { item: ChangeItem; showObserved?: boolean }) {
  const { timezone } = useOrgClock();
  const evidence = item.evidence_json;
  const observed = proofTime(evidence.observed_at, timezone);
  const attempted = proofTime(evidence.attempted_at, timezone);
  const peers = evidence.peers ?? [];
  if (!observed && !attempted && peers.length === 0) return null;
  return (
    <div className="mt-2 text-xs text-muted-foreground">
      {showObserved && observed && <p>讀回於 {observed}</p>}
      {attempted && (!observed || item.verification_state === "unknown" || item.verification_state === "stale") && <p>本次嘗試於 {attempted}</p>}
      {peers.length > 0 && (
        <details className="mt-2 rounded-lg border border-border px-3 py-2">
          <summary className="cursor-pointer font-medium text-foreground focus-visible:outline-2 focus-visible:outline-ring">
            核對資料
          </summary>
          <div className="mt-2 space-y-3">
            {peers.map((peer, index) => {
              const currentTime = proofTime(peer.observed_at, timezone);
              const attemptTime = proofTime(peer.attempted_at, timezone);
              const previous = peer.previous_observation;
              const previousTime = proofTime(previous?.observed_at, timezone);
              return (
                <div key={peer.handoff_item_id}>
                  {peers.length > 1 && <p className="font-medium text-foreground">
                    {typeof peer.native_id === "string" ? `平台廣告 ${peer.native_id}` : `核對項目 ${index + 1}`}
                  </p>}
                  {typeof peer.setting_matches === "boolean" && <p>
                    {peer.setting_matches ? "設定相符" : "設定不符"}
                  </p>}
                  <p>{materialProofText(peer.material_evidence)}</p>
                  {currentTime && <p>讀回於 {currentTime}</p>}
                  {!currentTime && attemptTime && <p>本次嘗試於 {attemptTime}</p>}
                  {typeof peer.message === "string" && peers.length > 1 && <p>{peer.message}</p>}
                  {previous && <div className="mt-2 border-l-2 border-border pl-3">
                    <p className="font-medium">保留前次證據</p>
                    {previousTime && <p>前次讀回於 {previousTime}</p>}
                    {typeof previous.evidence.setting_matches === "boolean" && <p>
                      前次設定：{previous.evidence.setting_matches ? "相符" : "不符"}
                    </p>}
                    <p>前次素材：{materialProofText(previous.evidence.material_evidence)}</p>
                  </div>}
                </div>
              );
            })}
          </div>
        </details>
      )}
    </div>
  );
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
              <ReadbackProof item={item} />
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
