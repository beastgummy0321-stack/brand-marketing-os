import { Chip, GradeChip, KindMark } from "../patterns";
import type { ChangeItem } from "@/lib/adsChangeApi";
import type { QueueCleanup, QueueCleanupAd } from "@/lib/adsTriageApi";
import type { CleanupDrift } from "./changeFlow";
import { CostCell } from "./CleanupProposal";
import { Tile } from "./Tile";

type Mark = "close" | "added" | "dropped";
type Row = { id: string; name: string | null; ad: QueueCleanupAd | null; mark: Mark };

/** F28-I11: the confirm card of a cleanup (prototype v9 `confirmBody()` for kind `clean`, hash `d/clean/ok`) — 關 N 則、
 * 留 M 則 and the close list with grade chips and costs. Once a change set exists its items are the frozen close
 * list (prototype `q.frozen`); each is filled from the queue row's `cleanup` payload while the row is still open,
 * else it falls back to the item's own name (same live/fallback split as `PauseEvidence`/`BudgetEvidence`).
 *
 * F28-I15: with `drift` (the draft's close list is not the queue row's current one, `changeFlow.ts::cleanupDrift`)
 * the card shows the latest proposal — its count, then its close list with the ads the draft did not have marked
 * 新增 — followed by the draft's ads the latest proposal no longer closes, struck through and marked 不關. */
export function CleanupEvidence({ cleanup, items, drift = null }: {
  cleanup: QueueCleanup | null; items: ChangeItem[]; drift?: CleanupDrift | null;
}) {
  const pool = new Map([...(cleanup?.ads ?? []), ...(cleanup?.keep ?? [])].map((ad) => [ad.entity_id, ad]));
  let rows: Row[];
  let keep: number | null;
  if (drift && cleanup) {
    const added = new Set(drift.added.map((ad) => ad.entity_id));
    rows = [
      ...cleanup.ads.map((ad): Row => ({ id: ad.entity_id, name: ad.name, ad, mark: added.has(ad.entity_id) ? "added" : "close" })),
      ...drift.dropped.map((item): Row => ({
        id: item.target_id, name: pool.get(item.target_id)?.name ?? item.target.name, ad: pool.get(item.target_id) ?? null, mark: "dropped",
      })),
    ];
    keep = cleanup.keep.length;
  } else {
    rows = items.length
      ? items.map((item): Row => ({ id: item.target_id, name: pool.get(item.target_id)?.name ?? item.target.name, ad: pool.get(item.target_id) ?? null, mark: "close" }))
      : (cleanup?.ads ?? []).map((ad): Row => ({ id: ad.entity_id, name: ad.name, ad, mark: "close" }));
    keep = cleanup ? pool.size - rows.filter((row) => row.ad).length : null;
  }
  const closing = rows.filter((row) => row.mark !== "dropped").length;
  return (
    <div className="surface px-[22px] py-5" data-drift={drift ? "true" : undefined}>
      <div className="flex flex-wrap items-start gap-5">
        <div className="min-w-[240px] flex-1">
          <KindMark kind="cut">清理</KindMark>
          <p className="mt-1.5 text-[26px] font-semibold tracking-tight">
            關 {closing} 則{keep !== null && `、留 ${keep} 則`}
          </p>
        </div>
        {drift && <Chip tone="warn">提議已更新</Chip>}
        <Chip tone="ok">✓ 不會新增花費</Chip>
      </div>
      <ul className="mt-3.5">
        {rows.map((row) => (
          <li
            key={row.id}
            data-mark={drift ? row.mark : undefined}
            className={`grid ${drift ? "grid-cols-[32px_minmax(0,1fr)_90px_100px_48px]" : "grid-cols-[32px_minmax(0,1fr)_90px_100px_36px]"} items-center gap-3.5 border-t border-border py-[11px] first:border-t-0 ${row.mark === "dropped" ? "opacity-55" : ""}`}
          >
            <Tile url={row.ad?.thumbnail_url} size="sm" />
            {drift ? (
              <p className="flex min-w-0 flex-wrap items-center gap-2 text-sm font-medium [overflow-wrap:anywhere]">
                <span className={`min-w-0 ${row.mark === "dropped" ? "line-through" : ""}`}>{row.name ?? "（未命名廣告）"}</span>
                {row.mark === "added" && <Chip tone="warn">新增</Chip>}
              </p>
            ) : (
              <p className="text-sm font-medium [overflow-wrap:anywhere]">{row.name ?? "（未命名廣告）"}</p>
            )}
            {row.ad ? <GradeChip grade={row.ad.grade} /> : <span />}
            <div className="numeric text-right">{row.ad && <CostCell ad={row.ad} label="" withCaption />}</div>
            {row.mark === "dropped" ? <Chip tone="neutral">不關</Chip> : <Chip tone="bad">關</Chip>}
          </li>
        ))}
      </ul>
    </div>
  );
}
